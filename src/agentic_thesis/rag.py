import hashlib
import html
import math
import re
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from time import perf_counter
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi
import tiktoken

from agentic_thesis.models import (
    CitationSpan,
    ClaimDelta,
    DeltaStatus,
    DisclosureChunk,
    EvidenceItem,
    EvidencePack,
    ThesisDelta,
    ThesisSnapshot,
)


@dataclass(frozen=True)
class _FilingBlock:
    kind: Literal["heading", "paragraph", "list_item", "table_row"]
    text: str


class _FilingHTMLParser(HTMLParser):
    _BLOCK_TAGS = {"div", "p", "li", "section", "article"}
    _IGNORED_TAGS = {"head", "script", "style", "noscript", "svg", "ix:header", "ix:hidden"}
    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[_FilingBlock] = []
        self.buffer: list[str] = []
        self.block_kind: Literal["heading", "paragraph", "list_item"] = "paragraph"
        self.ignored_depth = 0
        self.in_table = 0
        self.row: list[str] | None = None
        self.row_headers: list[bool] = []
        self.cell: list[str] | None = None
        self.cell_is_header = False
        self.table_headers: list[str] | None = None
        self.table_group: str | None = None

    @staticmethod
    def _hidden(attrs: list[tuple[str, str | None]]) -> bool:
        values = {name.lower(): (value or "").lower() for name, value in attrs}
        style = values.get("style", "").replace(" ", "")
        return (
            "hidden" in values
            or values.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )

    @staticmethod
    def _normalize(parts: list[str]) -> str:
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def _flush(self) -> None:
        text = self._normalize(self.buffer)
        self.buffer = []
        if text:
            kind = self.block_kind
            if re.match(r"^Item\s+(?:\d+[A-Z]?|[A-Z])\.?\b", text, re.IGNORECASE):
                kind = "heading"
            self.blocks.append(_FilingBlock(kind, text))
        self.block_kind = "paragraph"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.ignored_depth:
            if tag not in self._VOID_TAGS:
                self.ignored_depth += 1
            return
        if tag in self._IGNORED_TAGS or self._hidden(attrs):
            if tag not in self._VOID_TAGS:
                self.ignored_depth = 1
            return
        if tag == "br" and not self.in_table:
            self.buffer.append(" ")
        elif tag == "table":
            self._flush()
            self.in_table += 1
            self.table_headers = None
            self.table_group = None
        elif self.in_table and tag == "tr":
            self.row = []
            self.row_headers = []
        elif self.in_table and tag in {"td", "th"}:
            self.cell = []
            self.cell_is_header = tag == "th"
        elif not self.in_table and tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self.block_kind = "heading"
        elif not self.in_table and tag in self._BLOCK_TAGS:
            self._flush()
            self.block_kind = "list_item" if tag == "li" else "paragraph"

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.ignored_depth and tag.lower() == "br":
            self.buffer.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.ignored_depth:
            self.ignored_depth -= 1
            return
        if self.in_table and tag in {"td", "th"} and self.cell is not None:
            self.row = self.row or []
            self.row.append(self._normalize(self.cell))
            self.row_headers.append(self.cell_is_header)
            self.cell = None
            return
        if self.in_table and tag == "tr" and self.row is not None:
            cells = [cell for cell in self.row if cell]
            if cells:
                if (self.row_headers and all(self.row_headers)) or self._looks_like_table_header(cells):
                    self.table_headers = cells
                elif len(cells) == 1 and not re.search(r"\d", cells[0]):
                    self.table_group = cells[0]
                else:
                    text = self._format_table_row(cells)
                    self.blocks.append(_FilingBlock("table_row", text))
            self.row = None
            self.row_headers = []
            return
        if tag == "table" and self.in_table:
            self.in_table -= 1
            self.table_headers = None
            self.table_group = None
            return
        if not self.in_table and (tag in self._BLOCK_TAGS or tag in {"h1", "h2", "h3", "h4", "h5", "h6"}):
            self._flush()

    def _format_table_row(self, cells: list[str]) -> str:
        context = []
        if self.table_group:
            context.append(self.table_group)
        if self.table_headers:
            context.append("Columns: " + " | ".join(self.table_headers))
        context.append("Row: " + " | ".join(cells))
        return "; ".join(context)

    @staticmethod
    def _looks_like_table_header(cells: list[str]) -> bool:
        if len(cells) < 2:
            return False
        return not any(
            re.search(r"(?:\$|\d[,.]\d|\d{5,}|\(\s*\d)", cell)
            or (re.search(r"\d", cell) and not re.fullmatch(r"(?:19|20)\d{2}", cell))
            for cell in cells
        )

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        value = html.unescape(data).strip()
        if not value:
            return
        if self.in_table and self.cell is not None:
            self.cell.append(value)
        elif not self.in_table:
            self.buffer.append(value)

    def close(self) -> None:
        super().close()
        self._flush()


_ITEM_HEADING = re.compile(
    r"^Item\s+(?:1A|1B|1C|2|3|4|5|6|7A|7|8|9A|9B|9C|10|11|12|13|14|15|16)\.?"
    r"(?:\s+[^.]{2,100})?",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARY = re.compile(r"[.!?][\"”’')\]]*\s+(?=[A-Z0-9(\"“])")
_ABBREVIATIONS = {"co.", "corp.", "dr.", "inc.", "mr.", "mrs.", "ms.", "no.", "u.s.", "vs."}


def _blocks(document: str) -> list[_FilingBlock]:
    if not re.search(r"<[A-Za-z!/][^>]*>", document):
        return [
            _FilingBlock("paragraph", re.sub(r"\s+", " ", part).strip())
            for part in re.split(r"\n\s*\n|\n", document)
            if part.strip()
        ]
    parser = _FilingHTMLParser()
    parser.feed(document)
    parser.close()
    return parser.blocks


def _sentence_parts(text: str) -> list[tuple[int, int, str]]:
    starts = [0]
    for match in _SENTENCE_BOUNDARY.finditer(text):
        prefix = text[: match.start() + 1].rstrip()
        last_word = prefix.rsplit(" ", 1)[-1].lower().rstrip("\"”’')]")
        if last_word in _ABBREVIATIONS or re.fullmatch(r"(?:[a-z]\.){2,}", last_word):
            continue
        starts.append(match.end())
    starts.append(len(text))
    parts = []
    for start, end in zip(starts, starts[1:]):
        value = text[start:end].strip()
        if value:
            value_start = text.find(value, start, end)
            parts.append((value_start, value_start + len(value), value))
    return parts


def _complete_sentence_parts(text: str) -> list[tuple[int, int, str]]:
    return [
        part
        for part in _sentence_parts(text)
        if re.search(r"[.!?][\"”’')\]]*$", part[2])
    ]


def html_to_text(document: str) -> str:
    return "\n".join(block.text for block in _blocks(document))


def chunk_filing(
    document: str,
    *,
    source_id: str,
    source_date: str,
    source_url: str = "",
    artifact_id: str = "",
    offset: int = 0,
    page_number: int | None = None,
    max_chars: int = 2_400,
) -> list[DisclosureChunk]:
    spans: list[tuple[str, CitationSpan]] = []
    document_is_html = bool(re.search(r"<[A-Za-z!/][^>]*>", document))
    cursor = offset
    current_section = "Unknown"
    block_index = 0
    for block in _blocks(document):
        heading = _ITEM_HEADING.match(block.text)
        if block.kind == "heading" or heading:
            current_section = (heading.group(0) if heading else block.text)[:120]
            continue
        if block.kind == "paragraph":
            sentences = _complete_sentence_parts(block.text)
            parts = sentences or ([] if document_is_html else _sentence_parts(block.text))
            values = [(value, "sentence") for _, _, value in parts]
        else:
            values = [(block.text, block.kind)]
        for value, kind in values:
            if spans:
                cursor += 1
            start = cursor
            end = start + len(value)
            digest = hashlib.sha256(
                f"{source_id}:{block_index}:{kind}:{value}".encode()
            ).hexdigest()[:16]
            spans.append(
                (
                    current_section,
                    CitationSpan(
                        span_id=f"{source_id}:s:{digest}",
                        kind=kind,
                        text=value,
                        start_char=start,
                        end_char=end,
                        page_number=page_number,
                    ),
                )
            )
            cursor = end
            block_index += 1

    chunks: list[DisclosureChunk] = []
    window: list[CitationSpan] = []
    window_section = "Unknown"

    def flush() -> None:
        if not window:
            return
        body = "\n".join(span.text for span in window)
        digest = hashlib.sha256(
            f"{source_id}:{window[0].span_id}:{window[-1].span_id}".encode()
        ).hexdigest()[:16]
        chunks.append(
            DisclosureChunk(
                chunk_id=f"{source_id}:{digest}",
                source_id=source_id,
                source_date=source_date,
                section=window_section,
                text=body,
                start_char=window[0].start_char,
                end_char=window[-1].end_char,
                source_url=source_url,
                artifact_id=artifact_id,
                page_number=page_number,
                citation_spans=list(window),
            )
        )
        window.clear()

    for span_section, span in spans:
        next_size = sum(len(item.text) + 1 for item in window) + len(span.text)
        if window and (span_section != window_section or next_size > max_chars):
            flush()
        if not window:
            window_section = span_section
        window.append(span)
    flush()
    return chunks


def canonical_text_from_chunks(chunks: list[DisclosureChunk]) -> str:
    spans = {
        span.span_id: span
        for chunk in chunks
        for span in chunk.citation_spans
    }
    ordered = sorted(spans.values(), key=lambda span: span.start_char)
    parts: list[str] = []
    cursor = 0
    for span in ordered:
        if span.start_char > cursor:
            parts.append("\n" * (span.start_char - cursor))
        parts.append(span.text)
        cursor = span.end_char
    return "".join(parts)


class _RankedIds(BaseModel):
    chunk_ids: list[str]


class OpenAIModel:
    """The concrete API implementation used outside deterministic tests."""

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        embedding_client: AsyncOpenAI | None = None,
        model: str = "gpt-5-mini",
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        self.client = client
        self.embedding_client = embedding_client or client
        self.model = model
        self.embedding_model = embedding_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), 20):
            response = await self.embedding_client.embeddings.create(
                model=self.embedding_model,
                input=texts[start : start + 20],
            )
            embeddings.extend(item.embedding for item in response.data)
        return embeddings

    async def rerank(self, query: str, candidates: list[DisclosureChunk]) -> list[str]:
        candidate_text = "\n\n".join(
            f"[{chunk.chunk_id}] {chunk.section}\n{chunk.text[:1200]}"
            for chunk in candidates
        )
        response = await self.client.responses.parse(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": "Rank every supplied chunk by relevance. Return chunk IDs only.",
                },
                {"role": "user", "content": f"Query: {query}\n\n{candidate_text}"},
            ],
            text_format=_RankedIds,
        )
        return response.output_parsed.chunk_ids

    async def analyze(
        self,
        thesis: ThesisSnapshot,
        evidence_packs: list[EvidencePack],
    ) -> ThesisDelta:
        prompt_packs = [
            {
                **pack.model_dump(exclude={"items"}),
                "items": [item.model_dump(exclude={"source_text"}) for item in pack.items],
            }
            for pack in evidence_packs
        ]
        response = await self.client.responses.parse(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Compare each thesis claim with only the supplied evidence. Use supported, weakened, "
                        "possibly_invalidated, or unknown. Cite evidence IDs. possibly_invalidated requires a "
                        "matched falsifier. Abstain when evidence is insufficient. Do not give investment advice."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Thesis: {thesis.model_dump_json()}\n\n"
                        f"Evidence packs: {prompt_packs}"
                    ),
                },
            ],
            text_format=ThesisDelta,
        )
        return response.output_parsed


@dataclass(frozen=True)
class RetrievalHit:
    chunk: DisclosureChunk
    score: float


class HybridRetriever:
    def __init__(
        self,
        chunks: list[DisclosureChunk],
        *,
        embed: Callable[[list[str]], Awaitable[list[list[float]]]],
        rerank: Callable[[str, list[DisclosureChunk]], Awaitable[list[str]]],
        qdrant_path: str | Path | None = None,
        collection_name: str = "chunks",
        qdrant: QdrantClient | None = None,
    ) -> None:
        self.chunks = chunks
        self.embed = embed
        self.rerank = rerank
        self.bm25 = (
            BM25Okapi([self.tokenize(self.search_text(chunk)) for chunk in chunks])
            if chunks
            else None
        )
        self.qdrant = (
            qdrant
            if qdrant is not None
            else QdrantClient(path=str(qdrant_path))
            if qdrant_path
            else QdrantClient(":memory:")
        )
        self._owns_qdrant = qdrant is None
        self.collection_name = collection_name
        self.by_id = {chunk.chunk_id: chunk for chunk in chunks}

    @staticmethod
    def tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    @staticmethod
    def search_text(chunk: DisclosureChunk) -> str:
        return f"{chunk.section}\n{chunk.text}"

    @staticmethod
    def deterministic_embeddings(texts: list[str], dimensions: int = 64) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * dimensions
            for token in HybridRetriever.tokenize(text):
                digest = hashlib.sha256(token.encode()).digest()
                vector[int.from_bytes(digest[:2]) % dimensions] += 1.0 if digest[2] % 2 else -1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors

    async def index(self) -> None:
        point_ids = {
            chunk.chunk_id: self._point_id(chunk.chunk_id) for chunk in self.chunks
        }
        collection_exists = self.qdrant.collection_exists(self.collection_name)
        existing = (
            {
                str(point.id)
                for point in self.qdrant.retrieve(
                    self.collection_name,
                    ids=list(point_ids.values()),
                    with_payload=False,
                )
            }
            if collection_exists
            else set()
        )
        missing = [
            chunk
            for chunk in self.chunks
            if point_ids[chunk.chunk_id] not in existing
        ]
        if not missing:
            return
        vectors = await self.embed([self.search_text(chunk) for chunk in missing])
        if not collection_exists:
            self.qdrant.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=len(vectors[0]),
                    distance=models.Distance.COSINE,
                ),
            )
        self.qdrant.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=point_ids[chunk.chunk_id],
                    vector=vector,
                    payload={"chunk_id": chunk.chunk_id},
                )
                for chunk, vector in zip(missing, vectors, strict=True)
            ],
        )

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))

    def close(self) -> None:
        if self._owns_qdrant:
            self.qdrant.close()

    def _bm25_ids(self, query: str, limit: int = 12) -> list[str]:
        if self.bm25 is None:
            return []
        scores = self.bm25.get_scores(self.tokenize(query))
        order = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:limit]
        return [self.chunks[index].chunk_id for index in order]

    async def _vector_ids(self, query: str, limit: int = 12) -> list[str]:
        vector = (await self.embed([query]))[0]
        response = self.qdrant.query_points(
            collection_name=self.collection_name,
            query=vector,
            query_filter=models.Filter(
                must=[
                    models.HasIdCondition(
                        has_id=[self._point_id(chunk.chunk_id) for chunk in self.chunks]
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
        )
        return [str(point.payload["chunk_id"]) for point in response.points]

    @staticmethod
    def rrf(rankings: list[list[str]], limit: int = 12, k: int = 60) -> list[tuple[str, float]]:
        scores: dict[str, float] = defaultdict(float)
        for ranking in rankings:
            for rank, chunk_id in enumerate(ranking, start=1):
                scores[chunk_id] += 1.0 / (k + rank)
        return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]

    async def search(
        self,
        query: str,
        *,
        mode: Literal["bm25", "vector", "hybrid", "rerank", "conditional"] = "conditional",
        limit: int = 5,
    ) -> list[RetrievalHit]:
        if mode in {"rerank", "conditional"}:
            return (
                await self.search_with_timings(
                    query,
                    limit=limit,
                    rerank_policy="always" if mode == "rerank" else "conditional",
                )
            )[0]
        bm25_ids = self._bm25_ids(query)
        if mode == "bm25":
            ranked = [(chunk_id, float(len(bm25_ids) - rank)) for rank, chunk_id in enumerate(bm25_ids)]
            return [RetrievalHit(self.by_id[chunk_id], score) for chunk_id, score in ranked[:limit]]
        vector_ids = await self._vector_ids(query)
        if mode == "vector":
            ranked = [(chunk_id, float(len(vector_ids) - rank)) for rank, chunk_id in enumerate(vector_ids)]
        else:
            ranked = self.rrf([bm25_ids, vector_ids])
        return [RetrievalHit(self.by_id[chunk_id], score) for chunk_id, score in ranked[:limit]]

    async def search_with_timings(
        self,
        query: str,
        *,
        limit: int = 5,
        rerank_policy: Literal["always", "conditional"] = "conditional",
    ) -> tuple[list[RetrievalHit], dict[str, float | bool]]:
        started = perf_counter()
        bm25_ids = self._bm25_ids(query)
        vector_ids = await self._vector_ids(query)
        ranked = self.rrf([bm25_ids, vector_ids])
        retrieval_ms = round((perf_counter() - started) * 1_000, 3)
        rerank_triggered = rerank_policy == "always" or self._retrievers_disagree(
            bm25_ids,
            vector_ids,
        )
        if not rerank_triggered:
            return (
                [
                    RetrievalHit(self.by_id[chunk_id], score)
                    for chunk_id, score in ranked[:limit]
                ],
                {
                    "retrieval_ms": retrieval_ms,
                    "rerank_ms": 0.0,
                    "rerank_triggered": False,
                },
            )
        started = perf_counter()
        ordered = await self.rerank(query, [self.by_id[chunk_id] for chunk_id, _ in ranked])
        known = [chunk_id for chunk_id in ordered if chunk_id in dict(ranked)]
        missing = [chunk_id for chunk_id, _ in ranked if chunk_id not in known]
        ids = known + missing
        hits = [
            RetrievalHit(self.by_id[chunk_id], float(len(ids) - rank))
            for rank, chunk_id in enumerate(ids[:limit])
        ]
        return hits, {
            "retrieval_ms": retrieval_ms,
            "rerank_ms": round((perf_counter() - started) * 1_000, 3),
            "rerank_triggered": True,
        }

    @staticmethod
    def _retrievers_disagree(bm25_ids: list[str], vector_ids: list[str]) -> bool:
        if not bm25_ids or not vector_ids:
            return False
        return (
            bm25_ids[0] != vector_ids[0]
            and len(set(bm25_ids[:3]) & set(vector_ids[:3])) < 2
        )


def recall_at_k(results: dict[str, list[str]], gold: dict[str, str], k: int) -> float:
    hits = sum(gold_id in results.get(query, [])[:k] for query, gold_id in gold.items())
    return hits / len(gold) if gold else 0.0


def gold_rank(ranking: list[str], gold_id: str) -> int | None:
    return ranking.index(gold_id) + 1 if gold_id in ranking else None


def mean_reciprocal_rank(results: dict[str, list[str]], gold: dict[str, str]) -> float:
    reciprocal_ranks = [
        1.0 / rank
        for query, gold_id in gold.items()
        if (rank := gold_rank(results.get(query, []), gold_id)) is not None
    ]
    return sum(reciprocal_ranks) / len(gold) if gold else 0.0


def anchor_matches(text: str, anchor: str) -> bool:
    normalized_text = " ".join(HybridRetriever.tokenize(text))
    normalized_anchor = " ".join(HybridRetriever.tokenize(anchor))
    return bool(normalized_anchor) and normalized_anchor in normalized_text


def anchor_rank(ranking: list[DisclosureChunk], anchor: str) -> int | None:
    return next(
        (
            rank
            for rank, chunk in enumerate(ranking, start=1)
            if anchor_matches(HybridRetriever.search_text(chunk), anchor)
        ),
        None,
    )


def anchor_recall_at_k(
    results: dict[str, list[DisclosureChunk]],
    gold: dict[str, str],
    k: int,
) -> float:
    hits = sum(
        anchor_rank(results.get(query, [])[:k], anchor) is not None
        for query, anchor in gold.items()
    )
    return hits / len(gold) if gold else 0.0


def anchor_mean_reciprocal_rank(
    results: dict[str, list[DisclosureChunk]],
    gold: dict[str, str],
) -> float:
    reciprocal_ranks = [
        1.0 / rank
        for query, anchor in gold.items()
        if (rank := anchor_rank(results.get(query, []), anchor)) is not None
    ]
    return sum(reciprocal_ranks) / len(gold) if gold else 0.0


def _citation_spans(chunk: DisclosureChunk) -> list[CitationSpan]:
    if chunk.citation_spans:
        return chunk.citation_spans
    return [
        CitationSpan(
            span_id=f"{chunk.chunk_id}:s:{index}",
            kind="sentence",
            text=value,
            start_char=chunk.start_char + start,
            end_char=chunk.start_char + end,
        )
        for index, (start, end, value) in enumerate(_sentence_parts(chunk.text))
    ]


def build_evidence_pack(
    claim_id: str,
    claim: str,
    hits: list[RetrievalHit],
    *,
    token_budget: int,
) -> EvidencePack:
    encoding = tiktoken.get_encoding("cl100k_base")
    unique = {hit.chunk.chunk_id: hit for hit in hits}
    ranked = sorted(unique.values(), key=lambda hit: hit.score, reverse=True)
    tokens_before = sum(len(encoding.encode(hit.chunk.text)) for hit in ranked)
    terms = set(HybridRetriever.tokenize(claim))
    primary: list[tuple[RetrievalHit, CitationSpan, int]] = []
    extras: list[tuple[RetrievalHit, CitationSpan, int]] = []
    seen_spans: set[str] = set()
    per_window_budget = max(1, token_budget // max(1, len(ranked) * 2))
    for hit in ranked:
        spans = sorted(
            _citation_spans(hit.chunk),
            key=lambda span: (
                len(terms & set(HybridRetriever.tokenize(span.text))),
                span.kind == "table_row",
            ),
            reverse=True,
        )
        window_tokens = 0
        for span in spans:
            if span.span_id not in seen_spans:
                overlap = len(terms & set(HybridRetriever.tokenize(span.text)))
                span_tokens = len(encoding.encode(span.text))
                target = (
                    primary
                    if window_tokens + span_tokens <= per_window_budget
                    else extras
                )
                target.append((hit, span, overlap))
                if target is primary:
                    window_tokens += span_tokens
                seen_spans.add(span.span_id)
    extras.sort(key=lambda item: (item[2], item[0].score), reverse=True)
    candidates = primary + extras
    items: list[EvidenceItem] = []
    used = 0
    for hit, span, _ in candidates:
        remaining = token_budget - used
        if remaining <= 0:
            break
        quote_tokens = len(encoding.encode(span.text))
        if not span.text or quote_tokens > remaining:
            continue
        evidence_id = f"e:{span.span_id}"
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                chunk_id=hit.chunk.chunk_id,
                source_id=hit.chunk.source_id,
                source_date=hit.chunk.source_date,
                section=hit.chunk.section,
                kind=span.kind,
                source_url=hit.chunk.source_url,
                artifact_id=hit.chunk.artifact_id,
                page_number=span.page_number or hit.chunk.page_number,
                start_char=span.start_char,
                end_char=span.end_char,
                source_start_char=hit.chunk.start_char,
                source_end_char=hit.chunk.end_char,
                quote=span.text,
                source_text=hit.chunk.text,
                score=hit.score,
            )
        )
        used += quote_tokens
    return EvidencePack(
        claim_id=claim_id,
        items=items,
        tokens_before=tokens_before,
        tokens_after=used,
        retained_evidence_ids=[item.evidence_id for item in items],
    )


def enforce_citations(
    delta: ThesisDelta,
    packs: list[EvidencePack],
    thesis: ThesisSnapshot | None = None,
) -> ThesisDelta:
    evidence = {
        pack.claim_id: {item.evidence_id: item for item in pack.items}
        for pack in packs
    }
    claims = {claim.claim_id: claim for claim in thesis.claims} if thesis else {}
    validated: list[ClaimDelta] = []
    for claim_delta in delta.claim_deltas:
        claim_evidence = evidence.get(claim_delta.claim_id, {})
        cited = [claim_evidence.get(evidence_id) for evidence_id in claim_delta.evidence_ids]
        claim = claims.get(claim_delta.claim_id)
        citations_valid = bool(cited) and all(
            item is not None
            and 0 <= item.start_char - item.source_start_char
            <= item.end_char - item.source_start_char
            <= len(item.source_text)
            and item.source_text[
                item.start_char - item.source_start_char:
                item.end_char - item.source_start_char
            ] == item.quote
            for item in cited
        )
        falsifier_valid = (
            claim_delta.status != DeltaStatus.POSSIBLY_INVALIDATED
            or (
                bool(claim_delta.matched_falsifier)
                and (
                    not thesis
                    or (
                        claim is not None
                        and claim_delta.matched_falsifier in claim.falsifiers
                    )
                )
            )
        )
        if claim_delta.status != DeltaStatus.UNKNOWN and (not citations_valid or not falsifier_valid):
            validated.append(
                claim_delta.model_copy(
                    update={
                        "status": DeltaStatus.UNKNOWN,
                        "explanation": f"Citation validation failed. {claim_delta.explanation}",
                        "evidence_ids": [],
                        "matched_falsifier": None,
                    }
                )
            )
        else:
            validated.append(claim_delta)
    return delta.model_copy(update={"claim_deltas": validated})
