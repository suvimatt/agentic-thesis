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
    ClaimDelta,
    DeltaStatus,
    DisclosureChunk,
    EvidenceItem,
    EvidencePack,
    ThesisDelta,
    ThesisSnapshot,
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = html.unescape(data).strip()
        if value:
            self.parts.append(value)


def html_to_text(document: str) -> str:
    parser = _TextExtractor()
    parser.feed(document)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def chunk_filing(
    document: str,
    *,
    accession: str,
    filing_date: str,
    source_url: str = "",
    max_chars: int = 2_000,
) -> list[DisclosureChunk]:
    text = html_to_text(document)
    chunks: list[DisclosureChunk] = []
    sections = list(
        re.finditer(
            r"\bItem\s+(?:1A|1B|1C|2|3|4|5|6|7A|7|8|9A|9B|9C|10|11|12|13|14|15|16)\.?(?:\s+[A-Z][A-Za-z &,/-]{2,80})?",
            text,
            re.IGNORECASE,
        )
    )
    for start in range(0, len(text), max_chars):
        end = min(start + max_chars, len(text))
        body = text[start:end]
        preceding = [match.group(0) for match in sections if match.start() <= start]
        section = preceding[-1] if preceding else "Unknown"
        digest = hashlib.sha256(f"{accession}:{start}:{end}:{body}".encode()).hexdigest()[:16]
        chunks.append(
            DisclosureChunk(
                chunk_id=f"{accession}:{digest}",
                accession=accession,
                filing_date=filing_date,
                section=section,
                text=body,
                start_char=start,
                end_char=end,
                source_url=source_url,
            )
        )
    return chunks


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
            f"[{chunk.chunk_id}] {chunk.text[:1200]}" for chunk in candidates
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
        self.bm25 = BM25Okapi([self.tokenize(chunk.text) for chunk in chunks])
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
        vectors = await self.embed([chunk.text for chunk in missing])
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
    def rrf(rankings: list[list[str]], limit: int = 8, k: int = 60) -> list[tuple[str, float]]:
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


def _trim_extractively(text: str, query: str, max_tokens: int) -> str:
    encoding = tiktoken.get_encoding("cl100k_base")
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    terms = set(HybridRetriever.tokenize(query))
    best = max(
        range(len(sentences)),
        key=lambda index: len(terms & set(HybridRetriever.tokenize(sentences[index]))),
    )
    excerpt = " ".join(sentences[max(0, best - 1) : best + 2])
    tokens = encoding.encode(excerpt)[:max_tokens]
    return encoding.decode(tokens).strip()


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
    source_count = len({hit.chunk.filing_date for hit in ranked}) or 1
    source_heads: list[RetrievalHit] = []
    seen_sources: set[str] = set()
    for hit in ranked:
        if hit.chunk.filing_date not in seen_sources:
            source_heads.append(hit)
            seen_sources.add(hit.chunk.filing_date)
    ordered = source_heads + [hit for hit in ranked if hit not in source_heads]
    items: list[EvidenceItem] = []
    used = 0
    for index, hit in enumerate(ordered):
        remaining = token_budget - used
        if remaining <= 0:
            break
        full_tokens = len(encoding.encode(hit.chunk.text))
        mandatory_source = index < len(source_heads)
        allowance = min(remaining, max(1, token_budget // source_count)) if mandatory_source else remaining
        quote = (
            hit.chunk.text
            if full_tokens <= allowance
            else _trim_extractively(hit.chunk.text, claim, allowance)
        )
        quote_tokens = len(encoding.encode(quote))
        if not quote or quote_tokens > remaining:
            continue
        evidence_id = f"e:{hit.chunk.chunk_id}"
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                chunk_id=hit.chunk.chunk_id,
                accession=hit.chunk.accession,
                filing_date=hit.chunk.filing_date,
                section=hit.chunk.section,
                source_url=hit.chunk.source_url,
                start_char=hit.chunk.start_char,
                end_char=hit.chunk.end_char,
                quote=quote,
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
            item is not None and item.quote in item.source_text for item in cited
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
