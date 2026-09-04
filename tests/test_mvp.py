import asyncio
import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient

from agentic_thesis.api import (
    SecEdgarClient,
    _sec_form_metadata,
    _sec_form_selected,
    create_app,
)
from agentic_thesis.models import (
    ArtifactInput,
    ClaimDelta,
    DeltaStatus,
    DisclosureChunk,
    ReviewDecision,
    ThesisClaim,
    ThesisDelta,
    ThesisSnapshot,
)
from agentic_thesis.rag import (
    HybridRetriever,
    OpenAIModel,
    RetrievalHit,
    anchor_matches,
    anchor_mean_reciprocal_rank,
    anchor_recall_at_k,
    build_evidence_pack,
    canonical_text_from_chunks,
    chunk_filing,
    enforce_citations,
    gold_rank,
    mean_reciprocal_rank,
    recall_at_k,
)
from agentic_thesis.workflow import AgenticThesisWorkflow


def test_installed_cli_fails_fast_with_all_missing_credentials(tmp_path: Path) -> None:
    package_data = files("agentic_thesis").joinpath("sample_data")
    assert package_data.joinpath("thesis_v1.json").is_file()
    assert package_data.joinpath("filings/aapl-2023-10-k.html").is_file()
    assert package_data.joinpath("filings/aapl-2024-10-k.html").is_file()

    root = Path(__file__).parents[1]
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "OPENAI_API_KEY",
            "EMBEDDING_API_KEY",
            "EMBEDDING_BASE_URL",
            "AGENTIC_THESIS_EMBEDDING_MODEL",
        }
    }
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentic_thesis.cli",
            "serve",
            "--data-dir",
            str(tmp_path / "state"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    for variable in (
        "OPENAI_API_KEY",
        "EMBEDDING_API_KEY",
        "EMBEDDING_BASE_URL",
        "AGENTIC_THESIS_EMBEDDING_MODEL",
    ):
        assert variable in result.stderr


def test_chunk_ids_are_stable() -> None:
    html = "<html><body><h2>Item 1. Business</h2><p>Alpha beta gamma.</p></body></html>"

    first = chunk_filing(html, source_id="0001", source_date="2024-09-28", max_chars=20)
    second = chunk_filing(html, source_id="0001", source_date="2024-09-28", max_chars=20)

    assert first == second
    assert first
    assert all(isinstance(chunk, DisclosureChunk) for chunk in first)
    assert first[0].chunk_id.startswith("0001:")
    assert first[0].start_char < first[0].end_char


def test_financial_filing_chunks_preserve_atomic_citations() -> None:
    document = """
    <html><head><title>ignored</title></head><body>
      <div style="display:none"><ix:header>http://fasb.org/us-gaap hidden</ix:header></div>
      <input hidden value="ignored">
      <h2>Item 7. Management Discussion</h2>
      <p>Revenue in U.S. markets increased 12%. Demand remained durable.</p>
      <ul><li>Customer retention remained above 95%.</li></ul>
      <table>
        <tr><th>Metric</th><th>2024</th><th>2023</th></tr>
        <tr><td>Services margin</td><td>73.9%</td><td>70.8%</td></tr>
      </table>
    </body></html>
    """

    chunks = chunk_filing(
        document,
        source_id="atomic",
        source_date="2024-09-28",
        max_chars=60,
    )
    canonical_text = canonical_text_from_chunks(chunks)
    spans = [span for chunk in chunks for span in chunk.citation_spans]

    assert "hidden" not in canonical_text
    assert {span.kind for span in spans} == {"sentence", "list_item", "table_row"}
    assert [span.text for span in spans if span.kind == "sentence"] == [
        "Revenue in U.S. markets increased 12%.",
        "Demand remained durable.",
    ]
    assert next(span.text for span in spans if span.kind == "table_row") == (
        "Columns: Metric | 2024 | 2023; "
        "Row: Services margin | 73.9% | 70.8%"
    )
    assert all(
        canonical_text[span.start_char:span.end_char] == span.text
        for span in spans
    )
    assert all(
        span in chunk.citation_spans
        and chunk.text[
            span.start_char - chunk.start_char:span.end_char - chunk.start_char
        ] == span.text
        for chunk in chunks
        for span in chunk.citation_spans
    )

    plain_text = chunk_filing(
        "Management outlook unchanged",
        source_id="txt-1",
        source_date="2024-09-28",
    )
    assert plain_text[0].citation_spans[0].text == "Management outlook unchanged"


def test_fixed_sec_filings_exist() -> None:
    filings = files("agentic_thesis").joinpath("sample_data", "filings")
    assert len(filings.joinpath("aapl-2023-10-k.html").read_bytes()) > 1_000_000
    assert len(filings.joinpath("aapl-2024-10-k.html").read_bytes()) > 1_000_000


def test_gold_rank_reports_one_based_position_or_missing() -> None:
    assert gold_rank(["distractor", "gold", "other"], "gold") == 2
    assert gold_rank(["distractor", "other"], "gold") is None


def test_delta_gold_covers_two_companies_and_all_decisions() -> None:
    root = Path(__file__).parents[1]
    cases = json.loads((root / "evals/delta_gold.json").read_text())

    assert len({case["company"] for case in cases}) == 2
    assert {case["expected_status"] for case in cases} == {
        "supported",
        "weakened",
        "possibly_invalidated",
        "unknown",
    }
    assert all(
        case["evidence_anchor"] in case["disclosure"]["content"]
        for case in cases
    )
    assert sorted(
        case["sequence"] for case in cases if case["company"] == "Apple Inc."
    ) == [1, 2]


async def test_hybrid_retrieval_reports_measured_recall_at_5() -> None:
    root = Path(__file__).parents[1]
    chunks = [
        chunk
        for accession, filing_date, filename in (
            ("aapl-2023", "2023-09-30", "aapl-2023-10-k.html"),
            ("aapl-2024", "2024-09-28", "aapl-2024-10-k.html"),
        )
        for chunk in chunk_filing(
            files("agentic_thesis")
            .joinpath("sample_data", "filings", filename)
            .read_text(errors="ignore"),
            source_id=accession,
            source_date=filing_date,
        )
    ]
    cases = json.loads((root / "evals/gold.json").read_text())
    assert len(cases) >= 20
    assert {case["split"] for case in cases} == {"calibration", "held_out"}
    assert {
        "lexical",
        "numeric",
        "semantic",
        "risk",
        "regulatory",
    }.issubset({case["category"] for case in cases})
    gold = {case["query"]: case["anchor"] for case in cases}
    assert all(
        any(anchor_matches(chunk.text, case["anchor"]) for chunk in chunks)
        for case in cases
    )

    async def embed(texts: list[str]) -> list[list[float]]:
        return HybridRetriever.deterministic_embeddings(texts, dimensions=512)

    async def rerank(query: str, candidates: list[DisclosureChunk]) -> list[str]:
        terms = set(HybridRetriever.tokenize(query))
        return [
            chunk.chunk_id
            for chunk in sorted(
                candidates,
                key=lambda chunk: len(terms & set(HybridRetriever.tokenize(chunk.text))),
                reverse=True,
            )
        ]

    retriever = HybridRetriever(chunks, embed=embed, rerank=rerank)
    await retriever.index()
    results = {
        mode: {
            query: [hit.chunk for hit in await retriever.search(query, mode=mode, limit=5)]
            for query in gold
        }
        for mode in ("bm25", "vector", "hybrid", "rerank", "conditional")
    }
    metrics = {
        mode: anchor_recall_at_k(result, gold, 5)
        for mode, result in results.items()
    }

    assert metrics == {
        "bm25": 24 / 26,
        "vector": 15 / 26,
        "hybrid": 23 / 26,
        "rerank": 25 / 26,
        "conditional": 25 / 26,
    }
    assert {
        mode: round(anchor_mean_reciprocal_rank(mode_results, gold), 3)
        for mode, mode_results in results.items()
    } == {
        "bm25": 0.653,
        "vector": 0.438,
        "hybrid": 0.628,
        "rerank": 0.75,
        "conditional": 0.756,
    }
    vectors = [await retriever._vector_ids(query) for query in gold]
    assert sum(
        retriever._retrievers_disagree(retriever._bm25_ids(query), vector_ids)
        for query, vector_ids in zip(gold, vectors, strict=True)
    ) == 15
    held_out = {
        case["query"]: case["anchor"]
        for case in cases
        if case["split"] == "held_out"
    }
    assert anchor_recall_at_k(results["conditional"], held_out, 5) == 1.0, [
        query
        for query, anchor in held_out.items()
        if not any(anchor_matches(chunk.text, anchor) for chunk in results["conditional"][query])
    ]
    assert round(anchor_mean_reciprocal_rank(results["conditional"], held_out), 3) == 0.72
    for case in cases:
        hits = await retriever.search(case["query"], mode="rerank", limit=5)
        pack = build_evidence_pack("gold-eval", case["query"], hits, token_budget=2_000)
        if any(anchor_matches(hit.chunk.text, case["anchor"]) for hit in hits):
            assert any(
                anchor_matches(item.quote, case["anchor"])
                for item in pack.items
            ), (case["query"], [item.quote for item in pack.items])
        assert pack.tokens_after <= 2_000


async def test_conditional_rerank_only_runs_when_retrievers_disagree() -> None:
    assert HybridRetriever._retrievers_disagree(
        ["a", "b", "c"], ["d", "e", "a"]
    )
    assert not HybridRetriever._retrievers_disagree(
        ["a", "b", "c"], ["d", "a", "b"]
    )
    assert not HybridRetriever._retrievers_disagree(
        ["a", "b", "c"], ["a", "d", "e"]
    )

    chunks = [
        DisclosureChunk(
            chunk_id="services",
            source_id="test",
            source_date="2024-01-01",
            section="Services",
            text="Services revenue and gross margin increased.",
            start_char=0,
            end_char=44,
        ),
        DisclosureChunk(
            chunk_id="hardware",
            source_id="test",
            source_date="2024-01-01",
            section="Products",
            text="Hardware unit sales declined.",
            start_char=45,
            end_char=74,
        ),
    ]
    rerank_calls: list[str] = []

    async def rerank(query: str, candidates: list[DisclosureChunk]) -> list[str]:
        rerank_calls.append(query)
        return [chunk.chunk_id for chunk in candidates]

    async def agreeing_embed(texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0] if "services" in text.lower() else [0.0, 1.0]
            for text in texts
        ]

    agreeing = HybridRetriever(chunks, embed=agreeing_embed, rerank=rerank)
    await agreeing.index()
    agreeing_hits, agreeing_timings = await agreeing.search_with_timings(
        "services revenue margin",
        limit=2,
    )

    assert agreeing_hits[0].chunk.chunk_id == "services"
    assert agreeing_timings["rerank_triggered"] is False
    assert rerank_calls == []

    _, always_timings = await agreeing.search_with_timings(
        "services revenue margin",
        limit=2,
        rerank_policy="always",
    )
    assert always_timings["rerank_triggered"] is True
    assert rerank_calls == ["services revenue margin"]


async def test_persistent_vector_index_reuses_embeddings_and_scopes_search(
    tmp_path: Path,
) -> None:
    alpha = DisclosureChunk(
        chunk_id="alpha",
        source_id="test",
        source_date="2024-01-01",
        section="Business",
        text="Alpha recurring revenue expanded.",
        start_char=0,
        end_char=33,
    )
    beta = DisclosureChunk(
        chunk_id="beta",
        source_id="test",
        source_date="2024-01-01",
        section="Risk",
        text="Beta customer concentration increased.",
        start_char=34,
        end_char=72,
    )
    embedding_batches: list[list[str]] = []

    async def embed(texts: list[str]) -> list[list[float]]:
        embedding_batches.append(texts.copy())
        return HybridRetriever.deterministic_embeddings(texts)

    async def rerank(query: str, candidates: list[DisclosureChunk]) -> list[str]:
        return [chunk.chunk_id for chunk in candidates]

    options = {
        "embed": embed,
        "rerank": rerank,
        "qdrant_path": tmp_path / "qdrant",
        "collection_name": "persistent-test",
    }
    first = HybridRetriever([alpha], **options)
    await first.index()
    assert embedding_batches == [[HybridRetriever.search_text(alpha)]]
    first.close()

    restarted = HybridRetriever([alpha], **options)
    await restarted.index()
    assert embedding_batches == [[HybridRetriever.search_text(alpha)]]
    restarted.close()

    expanded = HybridRetriever([alpha, beta], **options)
    await expanded.index()
    assert embedding_batches == [
        [HybridRetriever.search_text(alpha)],
        [HybridRetriever.search_text(beta)],
    ]
    expanded.close()

    scoped = HybridRetriever([alpha], **options)
    await scoped.index()
    hits = await scoped.search("beta concentration", mode="vector", limit=1)
    assert [hit.chunk.chunk_id for hit in hits] == ["alpha"]
    scoped.close()


def test_evidence_pack_respects_budget_and_rejects_forged_quote() -> None:
    chunks = [
        DisclosureChunk(
            chunk_id="baseline",
            source_id="old",
            source_date="2023-09-30",
            section="Gross Margin",
            text="Services gross margin was 70.8 percent. " + "Baseline detail. " * 80,
            start_char=0,
            end_char=1300,
        ),
        DisclosureChunk(
            chunk_id="new",
            source_id="new",
            source_date="2024-09-28",
            section="Gross Margin",
            text="Products gross margin was 37.2 percent. Services gross margin was 73.9 percent. "
            + "New filing detail. " * 80,
            start_char=0,
            end_char=1400,
        ),
    ]
    pack = build_evidence_pack(
        "services-margin",
        "Services mix supports durable consolidated gross margins.",
        [RetrievalHit(chunks[0], 0.8), RetrievalHit(chunks[1], 0.9)],
        token_budget=80,
    )

    assert pack.tokens_after <= 80 < pack.tokens_before
    assert {item.source_date for item in pack.items} == {"2023-09-30", "2024-09-28"}
    assert any("Services gross margin" in item.quote for item in pack.items)
    valid = ThesisDelta(
        base_thesis_version=1,
        claim_deltas=[
            ClaimDelta(
                claim_id="services-margin",
                status=DeltaStatus.SUPPORTED,
                explanation="Services margin increased.",
                evidence_ids=[pack.items[1].evidence_id],
            )
        ],
    )
    assert enforce_citations(valid, [pack]).claim_deltas[0].status == DeltaStatus.SUPPORTED

    original_quote = pack.items[1].quote
    pack.items[1].quote = "A fabricated sentence that never appeared in the filing."
    rejected = enforce_citations(valid, [pack]).claim_deltas[0]
    assert rejected.status == DeltaStatus.UNKNOWN
    assert rejected.evidence_ids == []

    pack.items[1].quote = original_quote
    pack.items[1].end_char += 1
    rejected = enforce_citations(valid, [pack]).claim_deltas[0]
    assert rejected.status == DeltaStatus.UNKNOWN
    assert rejected.evidence_ids == []


async def test_structured_analysis_receives_compressed_quotes_not_source_chunks() -> None:
    chunk = DisclosureChunk(
        chunk_id="new",
        source_id="new",
        source_date="2024-09-28",
        section="Gross Margin",
        text="Services gross margin was 73.9 percent. Nearby context. "
        + "Unselected source-only detail. " * 100,
        start_char=0,
        end_char=2040,
    )
    pack = build_evidence_pack(
        "services-margin",
        "Services mix supports margins.",
        [RetrievalHit(chunk, 1.0)],
        token_budget=30,
    )
    thesis = ThesisSnapshot(
        thesis_id="aapl-primary",
        company="Apple Inc.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="services-margin",
                statement="Services mix supports margins.",
                rationale="Services has higher margins.",
            )
        ],
    )
    delta = ThesisDelta(
        base_thesis_version=1,
        claim_deltas=[
            ClaimDelta(
                claim_id="services-margin",
                status=DeltaStatus.SUPPORTED,
                explanation="Services margin remains high.",
                evidence_ids=[pack.items[0].evidence_id],
            )
        ],
    )

    class FakeResponses:
        input: list

        async def parse(self, **kwargs):
            self.input = kwargs["input"]
            return SimpleNamespace(output_parsed=delta)

    class FakeEmbeddings:
        calls: list[int] = []

        async def create(self, **kwargs):
            self.model = kwargs["model"]
            self.calls.append(len(kwargs["input"]))
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[1.0, 0.0]) for _ in kwargs["input"]]
            )

    client = SimpleNamespace(responses=FakeResponses())
    embedding_client = SimpleNamespace(embeddings=FakeEmbeddings())
    model = OpenAIModel(
        client,
        embedding_client=embedding_client,
        embedding_model="separate-embedding-model",
    )
    assert len(await model.embed(["query"] * 21)) == 21
    assert embedding_client.embeddings.calls == [20, 1]
    assert embedding_client.embeddings.model == "separate-embedding-model"
    await model.analyze(thesis, [pack])
    prompt = client.responses.input[1]["content"]

    assert pack.items[0].quote in prompt
    assert chunk.text not in prompt
    assert prompt.count("Unselected source-only detail") < 100
    assert "source_text" not in prompt


async def test_embedding_requests_use_the_separate_embedding_client() -> None:
    class WrongEmbeddings:
        async def create(self, **kwargs):
            raise AssertionError("embedding request reached the language-model service")

    class Embeddings:
        async def create(self, **kwargs):
            assert kwargs == {"model": "provider-embedding", "input": ["Apple services"]}
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.25, 0.75])])

    model = OpenAIModel(
        SimpleNamespace(embeddings=WrongEmbeddings()),
        embedding_client=SimpleNamespace(embeddings=Embeddings()),
        embedding_model="provider-embedding",
    )

    assert await model.embed(["Apple services"]) == [[0.25, 0.75]]


async def test_app_shutdown_waits_for_inflight_run_cancellation(tmp_path: Path) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    thesis = ThesisSnapshot(
        thesis_id="shutdown-test",
        company="Apple Inc.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="services-margin",
                statement="Services mix supports margins.",
                rationale="Services has higher margins.",
            )
        ],
    )
    content = "<p>Services gross margin was 73.9 percent.</p>"
    chunks = chunk_filing(content, source_id="new", source_date="2024-09-28")

    class BlockingRetriever:
        async def search_with_timings(self, query: str, *, limit: int):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    async def analyze(snapshot: ThesisSnapshot, packs: list) -> ThesisDelta:
        raise AssertionError("analysis should not run before cancellation")

    workflow = await AgenticThesisWorkflow.create(
        tmp_path / "shutdown.sqlite",
        BlockingRetriever(),
        analyze,
    )
    app = create_app(workflow)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/theses", json=thesis.model_dump(mode="json"))
            await client.post(
                "/disclosures",
                json={
                    "document_id": "new",
                    "thesis_id": thesis.thesis_id,
                    "source_id": "new",
                    "source_date": "2024-09-28",
                    "content": content,
                },
            )
            response = await client.post(
                "/runs",
                json={
                    "run_id": "shutdown-run",
                    "thesis_id": thesis.thesis_id,
                    "disclosure_id": "new",
                },
            )
            assert response.status_code == 202
            await started.wait()

    assert cancelled.is_set()
    assert app.state.run_tasks["shutdown-run"].done()
    await workflow.close()

    class ResumedRetriever:
        async def search_with_timings(self, query: str, *, limit: int):
            return [RetrievalHit(chunks[0], 1.0)], {"retrieval_ms": 1.0, "rerank_ms": 1.0}

    async def resumed_analyze(snapshot: ThesisSnapshot, packs: list) -> ThesisDelta:
        return ThesisDelta(
            base_thesis_version=snapshot.version,
            claim_deltas=[
                ClaimDelta(
                    claim_id="services-margin",
                    status=DeltaStatus.SUPPORTED,
                    explanation="Services margin remains high.",
                    evidence_ids=[packs[0].items[0].evidence_id],
                )
            ],
        )

    restarted = await AgenticThesisWorkflow.create(
        tmp_path / "shutdown.sqlite",
        ResumedRetriever(),
        resumed_analyze,
    )
    restarted_app = create_app(restarted)
    async with restarted_app.router.lifespan_context(restarted_app):
        async with AsyncClient(
            transport=ASGITransport(app=restarted_app), base_url="http://test"
        ) as client:
            async with asyncio.timeout(2):
                events = await client.get("/runs/shutdown-run/events")
            assert '"status": "awaiting_review"' in events.text
    assert not restarted_app.state.run_tasks["shutdown-run"].cancelled()
    assert restarted_app.state.run_tasks["shutdown-run"].exception() is None
    await restarted.close()


async def test_langgraph_resumes_after_restart_and_rejects_stale_commit(tmp_path: Path) -> None:
    thesis = ThesisSnapshot(
        thesis_id="aapl-primary",
        company="Apple Inc.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="services-margin",
                statement="Services mix supports margins.",
                rationale="Services has higher margins.",
                falsifiers=["Services margin declines"],
            )
        ],
    )
    content = "<p>Services gross margin was 73.9 percent.</p>"
    chunks = chunk_filing(content, source_id="new", source_date="2024-09-28")

    class FakeRetriever:
        async def search(self, query: str, *, mode: str, limit: int) -> list[RetrievalHit]:
            return [RetrievalHit(chunks[0], 1.0)]

        async def search_with_timings(
            self,
            query: str,
            *,
            limit: int,
        ) -> tuple[list[RetrievalHit], dict[str, float]]:
            return [RetrievalHit(chunks[0], 1.0)], {
                "retrieval_ms": 1.25,
                "rerank_ms": 2.5,
            }

    async def analyze(snapshot: ThesisSnapshot, packs: list) -> ThesisDelta:
        if snapshot.thesis_id == "aapl-error":
            raise TimeoutError("model timed out")
        return ThesisDelta(
            base_thesis_version=snapshot.version,
            claim_deltas=[
                ClaimDelta(
                    claim_id="services-margin",
                    status=DeltaStatus.SUPPORTED,
                    explanation="Services margin remains high.",
                    evidence_ids=[packs[0].items[0].evidence_id],
                )
            ],
        )

    database = tmp_path / "state.sqlite"
    first = await AgenticThesisWorkflow.create(database, FakeRetriever(), analyze)
    await first.create_thesis(thesis)
    await first.register_run("resume-run", thesis, "new")
    paused = await first.start("resume-run", "new", thesis, chunks)
    assert paused["__interrupt__"]
    await first.close()

    restarted = await AgenticThesisWorkflow.create(database, FakeRetriever(), analyze)
    committed = await restarted.resume("resume-run", ReviewDecision(action="approve"))
    assert committed["status"] == "committed"
    assert committed["thesis"].version == 2

    await restarted.register_run("conflict-run", committed["thesis"], "new")
    conflict_paused = await restarted.start(
        "conflict-run", "new", committed["thesis"], chunks
    )
    assert conflict_paused["__interrupt__"]
    await restarted.advance_head("aapl-primary")
    await restarted.close()

    restarted_again = await AgenticThesisWorkflow.create(database, FakeRetriever(), analyze)
    conflicted = await restarted_again.resume("conflict-run", ReviewDecision(action="approve"))
    assert conflicted["status"] == "version_conflict"
    assert conflicted["error"] == "base thesis version is stale"

    api_thesis = thesis.model_copy(update={"thesis_id": "aapl-api"})
    app = create_app(restarted_again)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert "Track why you own a company" in page.text
        assert "what would prove you wrong" in page.text
        assert "What changed in your company thesis" in page.text
        assert "Review the proposed update" in page.text
        assert "Recent checks" in page.text
        assert 'id="runs"' in page.text
        assert "Create a company thesis" in page.text
        assert 'id="thesis-company"' in page.text
        assert 'id="thesis-claims"' in page.text
        assert 'id="add-thesis-claim"' in page.text
        assert 'class="thesis-claim"' in page.text
        assert "Why do you believe this?" in page.text
        assert "What fact would prove this wrong?" in page.text
        assert "Investment case JSON" not in page.text
        assert 'id="thesis-json"' not in page.text
        assert "Add a source document manually" in page.text
        assert "Keep my current view" in page.text
        assert "Save this evidence update" in page.text
        assert "Still supported" in page.text
        assert "May no longer hold" in page.text
        assert "Monitor a thesis" not in page.text
        assert "Review thesis changes" not in page.text
        assert "A stale base version returns HTTP 409" not in page.text
        assert "ThesisSnapshot v1" not in page.text

        guided_thesis = {
            "thesis_id": "guided-test",
            "company": "Example Co.",
            "version": 1,
            "claims": [
                {
                    "claim_id": "reason-1",
                    "statement": "Recurring revenue supports durable cash flow.",
                    "rationale": "Renewals make revenue more predictable.",
                    "falsifiers": ["Renewal rates decline for a sustained period."],
                    "evidence_refs": [],
                }
            ],
        }
        created = await client.post("/theses", json=guided_thesis)
        assert created.status_code == 201
        assert (await client.get("/theses/guided-test")).json() == guided_thesis

        await client.post("/theses", json=api_thesis.model_dump(mode="json"))
        await client.post(
            "/disclosures",
            json={
                "document_id": "api-new",
                "thesis_id": api_thesis.thesis_id,
                "source_id": "new",
                "source_date": "2024-09-28",
                "content": content,
            },
        )

        started = await client.post(
            "/runs",
            json={
                "run_id": "api-run",
                "thesis_id": api_thesis.thesis_id,
                "disclosure_id": "api-new",
            },
        )
        assert started.status_code == 202
        assert started.json()["status"] == "running"

        events = await client.get("/runs/api-run/events")
        assert events.headers["content-type"].startswith("text/event-stream")
        assert '"node": "retrieve_claims"' in events.text
        assert '"retrieval_ms": 2.5' in events.text
        assert '"rerank_ms": 5.0' in events.text
        assert '"total_ms":' in events.text
        assert '"tokens_after"' in events.text
        assert '"status": "awaiting_review"' in events.text
        assert app.state.run_tasks["api-run"].done()
        assert (await client.get("/runs/api-run")).json()["status"] == "awaiting_review"

        reviewed = await client.post("/runs/api-run/review", json={"action": "approve"})
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "committed"
        repeated_review = await client.post(
            "/runs/api-run/review",
            json={"action": "reject"},
        )
        assert repeated_review.status_code == 409
        assert repeated_review.json()["detail"] == "run is not awaiting review"

        latest_started = await client.post(
            "/runs",
            json={
                "run_id": "api-latest",
                "thesis_id": api_thesis.thesis_id,
                "disclosure_id": "api-new",
            },
        )
        assert latest_started.status_code == 202
        async with asyncio.timeout(2):
            await client.get("/runs/api-latest/events")
        latest_state = (await client.get("/runs/api-latest")).json()
        assert latest_state["thesis"]["version"] == 2
        invalid_review = await client.post(
            "/runs/api-latest/review",
            json={
                "action": "approve",
                "edited_delta": {
                    "base_thesis_version": 2,
                    "claim_deltas": [],
                },
            },
        )
        assert invalid_review.status_code == 422
        assert (await client.get("/runs/api-latest")).json()["status"] == "invalid_review"
        assert (await restarted_again.list_events("api-latest"))[-1][1][
            "status"
        ] == "invalid_review"

        conflict_started = await client.post(
            "/runs",
            json={
                "run_id": "api-conflict",
                "thesis_id": api_thesis.thesis_id,
                "disclosure_id": "api-new",
            },
        )
        assert conflict_started.status_code == 202
        await client.get("/runs/api-conflict/events")
        await restarted_again.advance_head("aapl-api")
        conflict_response = await client.post(
            "/runs/api-conflict/review",
            json={"action": "approve"},
        )
        assert conflict_response.status_code == 409
        conflict_history = await client.get("/runs", params={"thesis_id": "aapl-api"})
        assert next(
            run for run in conflict_history.json() if run["run_id"] == "api-conflict"
        )["status"] == "version_conflict"

        error_thesis = thesis.model_copy(update={"thesis_id": "aapl-error"})
        await client.post("/theses", json=error_thesis.model_dump(mode="json"))
        await client.post(
            "/disclosures",
                json={
                    "document_id": "error-new",
                    "thesis_id": error_thesis.thesis_id,
                    "source_id": "new",
                "source_date": "2024-09-28",
                "content": content,
            },
        )
        error_started = await client.post(
            "/runs",
            json={
                "run_id": "api-error",
                "thesis_id": error_thesis.thesis_id,
                "disclosure_id": "error-new",
            },
        )
        assert error_started.status_code == 202
        error_events = await client.get("/runs/api-error/events")
        assert '"status": "failed"' in error_events.text
        assert "model timed out" in error_events.text
        error_state = (await client.get("/runs/api-error")).json()
        assert error_state["status"] == "failed"
        assert error_state["error"] == "model timed out"
    await restarted_again.close()


async def test_run_history_and_sse_replay_survive_restart(tmp_path: Path) -> None:
    thesis = ThesisSnapshot(
        thesis_id="history-thesis",
        company="Apple Inc.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="services-margin",
                statement="Services mix supports margins.",
                rationale="Services has higher margins.",
            )
        ],
    )
    content = "<p>Services gross margin was 73.9 percent.</p>"
    chunk = chunk_filing(
        content, source_id="history", source_date="2024-09-28"
    )[0]

    class FakeRetriever:
        async def search_with_timings(self, query: str, *, limit: int):
            return [RetrievalHit(chunk, 1.0)], {"retrieval_ms": 1.0, "rerank_ms": 1.0}

    async def analyze(snapshot: ThesisSnapshot, packs: list) -> ThesisDelta:
        return ThesisDelta(
            base_thesis_version=snapshot.version,
            claim_deltas=[
                ClaimDelta(
                    claim_id="services-margin",
                    status=DeltaStatus.SUPPORTED,
                    explanation="Services margin remains high.",
                    evidence_ids=[packs[0].items[0].evidence_id],
                )
            ],
        )

    database = tmp_path / "history.sqlite"
    first = await AgenticThesisWorkflow.create(database, FakeRetriever(), analyze)
    first_app = create_app(first)
    async with AsyncClient(
        transport=ASGITransport(app=first_app), base_url="http://test"
    ) as client:
        await client.post("/theses", json=thesis.model_dump(mode="json"))
        await client.post(
            "/disclosures",
            json={
                "document_id": "history-disclosure",
                "thesis_id": thesis.thesis_id,
                "source_id": "history",
                "source_date": "2024-09-28",
                "content": content,
            },
        )
        started = await client.post(
            "/runs",
            json={
                "run_id": "history-run",
                "thesis_id": thesis.thesis_id,
                "disclosure_id": "history-disclosure",
            },
        )
        assert started.status_code == 202
        async with asyncio.timeout(2):
            events = await client.get("/runs/history-run/events")
        assert "id: 1" in events.text
        assert '"status": "awaiting_review"' in events.text
        assert first_app.state.run_tasks["history-run"].done()
    await first.close()

    restarted = await AgenticThesisWorkflow.create(database, FakeRetriever(), analyze)
    restarted_app = create_app(restarted)
    async with AsyncClient(
        transport=ASGITransport(app=restarted_app), base_url="http://test"
    ) as client:
        history = await client.get("/runs")
        assert history.status_code == 200
        assert history.json() == [
            {
                "run_id": "history-run",
                "thesis_id": "history-thesis",
                "disclosure_id": "history-disclosure",
                "base_thesis_version": 1,
                "status": "awaiting_review",
                "committed_thesis_version": None,
                "error": None,
            }
        ]
        async with asyncio.timeout(2):
            replayed = await client.get(
                "/runs/history-run/events",
                headers={"Last-Event-ID": "2"},
            )
        assert "id: 1" not in replayed.text
        assert "id: 2" not in replayed.text
        assert "id: 3" in replayed.text
        assert '"status": "awaiting_review"' in replayed.text
    await restarted.close()


async def test_multiple_theses_use_only_their_own_manual_disclosures(tmp_path: Path) -> None:
    apple_chunk = DisclosureChunk(
        chunk_id="bootstrap",
        source_id="bootstrap",
        source_date="2024-01-01",
        section="Unknown",
        text="Bootstrap corpus.",
        start_char=0,
        end_char=17,
    )

    async def embed(texts: list[str]) -> list[list[float]]:
        return HybridRetriever.deterministic_embeddings(texts)

    async def rerank(query: str, candidates: list[DisclosureChunk]) -> list[str]:
        return [chunk.chunk_id for chunk in candidates]

    retriever = HybridRetriever([apple_chunk], embed=embed, rerank=rerank)
    await retriever.index()

    async def analyze(snapshot: ThesisSnapshot, packs: list) -> ThesisDelta:
        return ThesisDelta(
            base_thesis_version=snapshot.version,
            claim_deltas=[
                ClaimDelta(
                    claim_id=snapshot.claims[0].claim_id,
                    status=DeltaStatus.SUPPORTED,
                    explanation="The imported disclosure contains relevant evidence.",
                    evidence_ids=[packs[0].items[0].evidence_id],
                )
            ],
        )

    workflow = await AgenticThesisWorkflow.create(
        tmp_path / "multiple.sqlite", retriever, analyze
    )
    app = create_app(workflow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for thesis_id, company, keyword in (
            ("apple-custom", "Apple Inc.", "wearables"),
            ("microsoft-custom", "Microsoft Corp.", "cloud"),
        ):
            thesis = ThesisSnapshot(
                thesis_id=thesis_id,
                company=company,
                version=1,
                claims=[
                    ThesisClaim(
                        claim_id=f"{keyword}-claim",
                        statement=f"{keyword.title()} supports durable growth.",
                        rationale=f"{keyword.title()} is strategically important.",
                    )
                ],
            )
            created = await client.post("/theses", json=thesis.model_dump(mode="json"))
            assert created.status_code == 201
            disclosure = await client.post(
                "/disclosures",
                json={
                    "document_id": f"{thesis_id}-2024",
                    "thesis_id": thesis_id,
                    "source_id": f"{thesis_id}-accession",
                    "source_date": "2024-09-28",
                    "source_url": f"https://example.com/{thesis_id}",
                    "content": f"<html><body>{company} reported stronger {keyword} performance.</body></html>",
                },
            )
            assert disclosure.status_code == 201

        theses = await client.get("/theses")
        assert {item["thesis_id"] for item in theses.json()} == {
            "apple-custom",
            "microsoft-custom",
        }

        missing = await client.post(
            "/runs",
            json={
                "run_id": "missing-run",
                "thesis_id": "does-not-exist",
                "disclosure_id": "missing",
            },
        )
        assert missing.status_code == 404
        no_disclosures = ThesisSnapshot(
            thesis_id="no-disclosures",
            company="No Documents Inc.",
            version=1,
            claims=[
                ThesisClaim(
                    claim_id="empty",
                    statement="There is evidence.",
                    rationale="No disclosure has been imported.",
                )
            ],
        )
        assert (
            await client.post("/theses", json=no_disclosures.model_dump(mode="json"))
        ).status_code == 201
        no_disclosure_run = await client.post(
            "/runs",
            json={
                "run_id": "empty-run",
                "thesis_id": "no-disclosures",
                "disclosure_id": "missing",
            },
        )
        assert no_disclosure_run.status_code == 404

        for thesis_id, expected, excluded in (
            ("apple-custom", "wearables", "cloud"),
            ("microsoft-custom", "cloud", "wearables"),
        ):
            started = await client.post(
                "/runs",
                json={
                    "run_id": f"{thesis_id}-run",
                    "thesis_id": thesis_id,
                    "disclosure_id": f"{thesis_id}-2024",
                },
            )
            assert started.status_code == 202
            await client.get(f"/runs/{thesis_id}-run/events")
            state = (await client.get(f"/runs/{thesis_id}-run")).json()
            source_text = " ".join(
                item["quote"] for pack in state["evidence_packs"] for item in pack["items"]
            ).lower()
            assert expected in source_text
            assert excluded not in source_text
    await workflow.close()


async def test_sec_client_traverses_submission_history_and_collects_artifacts() -> None:
    cik = "0000320193"
    accession = "0000320193-24-000010"
    main = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-25-000079"],
                "filingDate": ["2025-08-01"],
                "form": ["8-K"],
                "primaryDocument": ["current.htm"],
                "acceptanceDateTime": ["2025-08-01T16:05:00.000Z"],
                "reportDate": ["2025-08-01"],
            },
            "files": [{"name": "CIK0000320193-submissions-001.json"}],
        }
    }
    older = {
        "accessionNumber": [accession],
        "filingDate": ["2024-05-01"],
        "form": ["8-K"],
        "primaryDocument": ["primary.htm"],
        "acceptanceDateTime": ["2024-05-01T12:00:00.000Z"],
        "reportDate": ["2024-05-01"],
    }
    index = b"""
    <table class="tableFile">
      <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
      <tr><td>1</td><td>Current report</td><td><a href="primary.htm">primary.htm</a></td><td>8-K</td><td>100</td></tr>
      <tr><td>2</td><td>Press release</td><td><a href="ex991.htm">ex991.htm</a></td><td>EX-99.1</td><td>100</td></tr>
      <tr><td>3</td><td>XBRL instance</td><td><a href="facts.xml">facts.xml</a></td><td>XML</td><td>100</td></tr>
      <tr><td>4</td><td>Graphic</td><td><a href="logo.jpg">logo.jpg</a></td><td>GRAPHIC</td><td>100</td></tr>
    </table>
    """
    base = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000010/"
    responses = {
        f"https://data.sec.gov/submissions/CIK{cik}.json": json.dumps(main).encode(),
        "https://data.sec.gov/submissions/CIK0000320193-submissions-001.json": json.dumps(older).encode(),
        base + accession + "-index.html": index,
        base + "primary.htm": b"<html><body>Primary evidence.</body></html>",
        base + "ex991.htm": b"<html><body>Exhibit evidence.</body></html>",
    }
    client = SecEdgarClient("AgenticThesis test@example.com")

    def read(url: str) -> bytes:
        if url.endswith("facts.xml"):
            raise TimeoutError("structured data timed out")
        return responses[url]

    client._read = read
    filings = await client.filings(cik, accession)
    assert [item["accession"] for item in filings] == [
        "0000320193-25-000079", accession
    ]
    artifacts, failures = await client.filing_artifacts(cik, filings[1])
    assert {artifact.role for artifact in artifacts} == {
        "filing_index", "primary_document", "exhibit"
    }
    assert failures == [
        {
            "role": "structured_data",
            "source_url": base + "facts.xml",
            "error": "structured data timed out",
        }
    ]


def test_sec_form_matrix_classifies_and_includes_amendments() -> None:
    expected = {
        "10-K": "periodic_report",
        "10-Q/A": "periodic_report",
        "8-K": "current_report",
        "DEF 14A": "proxy",
        "3": "insider_ownership",
        "4": "insider_ownership",
        "5": "insider_ownership",
        "SC 13D/A": "beneficial_ownership",
        "SC 13G": "beneficial_ownership",
        "13F-HR": "institutional_holdings",
        "N-PX": "other",
    }
    assert {
        form: _sec_form_metadata(form)["form_family"] for form in expected
    } == expected
    assert _sec_form_selected("10-K/A", ["10-K"])
    assert _sec_form_selected("SC 13D/A", ["SC 13D"])
    assert not _sec_form_selected("8-K", ["10-K"])


async def test_sec_sync_imports_one_new_filing_once_and_starts_review(
    tmp_path: Path,
) -> None:
    bootstrap = DisclosureChunk(
        chunk_id="bootstrap",
        source_id="bootstrap",
        source_date="2024-01-01",
        section="Business",
        text="Services are strategically important.",
        start_char=0,
        end_char=37,
    )

    async def embed(texts: list[str]) -> list[list[float]]:
        return HybridRetriever.deterministic_embeddings(texts)

    async def rerank(query: str, candidates: list[DisclosureChunk]) -> list[str]:
        return [chunk.chunk_id for chunk in candidates]

    retriever = HybridRetriever([bootstrap], embed=embed, rerank=rerank)
    await retriever.index()

    async def analyze(snapshot: ThesisSnapshot, packs: list) -> ThesisDelta:
        return ThesisDelta(
            base_thesis_version=snapshot.version,
            claim_deltas=[
                ClaimDelta(
                    claim_id="services",
                    status=DeltaStatus.SUPPORTED,
                    explanation="The filing supports the claim.",
                    evidence_ids=[packs[0].items[0].evidence_id],
                )
            ],
        )

    class FakeSec:
        async def filings(
            self, cik: str, after_accession: str | None = None
        ) -> list[dict[str, str]]:
            assert cik == "0000320193"
            return [
                {
                    "accession": "0000320193-25-000079",
                    "filing_date": "2025-08-01",
                    "form": "10-Q",
                    "primary_document": "aapl-20250628.htm",
                }
            ]

        async def filing_artifacts(self, cik: str, filing: dict[str, str]):
            url = (
                "https://www.sec.gov/Archives/edgar/data/320193/"
                "000032019325000079/aapl-20250628.htm"
            )
            return [ArtifactInput(
                role="primary_document",
                source_url=url,
                media_type="text/html",
                content=b"<html><body><h2>Item 2.</h2>Services revenue increased.</body></html>",
            )], []

    thesis = ThesisSnapshot(
        thesis_id="apple-monitor",
        company="Apple Inc.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="services",
                statement="Services remain strategically important.",
                rationale="Services diversify gross profit.",
            )
        ],
    )
    workflow = await AgenticThesisWorkflow.create(
        tmp_path / "sec-sync.sqlite", retriever, analyze
    )
    app = create_app(workflow, sec_client=FakeSec())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/theses", json=thesis.model_dump(mode="json"))
        ).status_code == 201
        configured = await client.put(
            "/theses/apple-monitor/monitor",
            json={"cik": "320193", "forms": ["10-Q", "10-K"], "enabled": True},
        )
        assert configured.status_code == 200
        assert configured.json()["cik"] == "0000320193"

        first = await client.post("/theses/apple-monitor/sync")
        assert first.status_code == 200
        assert first.json() == {
            "thesis_id": "apple-monitor",
            "checked": 1,
            "imported": 1,
            "run_ids": ["sec-apple-monitor-0000320193-25-000079"],
        }
        async with asyncio.timeout(2):
            events = await client.get(
                "/runs/sec-apple-monitor-0000320193-25-000079/events"
            )
        assert '"status": "awaiting_review"' in events.text
        assert app.state.run_tasks[
            "sec-apple-monitor-0000320193-25-000079"
        ].done()
        monitor = (await client.get("/monitors")).json()[0]
        assert monitor["last_accession"] == "0000320193-25-000079"
        assert monitor["last_imported"] == 1
        assert monitor["last_error"] is None
        attempts = (
            await client.get(
                "/collection-attempts", params={"thesis_id": "apple-monitor"}
            )
        ).json()
        assert attempts[0]["status"] == "succeeded"
        assert attempts[0]["cursor_after"] == "0000320193-25-000079"
        assert attempts[0]["imported"] == 1
        radar = (
            await client.get("/radar", params={"thesis_id": "apple-monitor"})
        ).json()
        assert radar[0]["outcome"] == "needs_review"
        assert radar[0]["reason_codes"] == ["high_impact_periodic_report"]
        assert radar[0]["run_id"] == "sec-apple-monitor-0000320193-25-000079"
        event = (await client.get(f"/events/{radar[0]['event_id']}")).json()
        assert event["metadata"]["form_family"] == "periodic_report"
        assert event["metadata"]["is_amendment"] == "false"
        assert len(
            (
                await client.get(
                    "/disclosures", params={"thesis_id": "apple-monitor"}
                )
            ).json()
        ) == 1
        assert len(
            (await client.get("/runs", params={"thesis_id": "apple-monitor"})).json()
        ) == 1

        second = await client.post("/theses/apple-monitor/sync")
        assert second.status_code == 200
        assert second.json()["imported"] == 0
        assert second.json()["run_ids"] == []
        assert len(
            (
                await client.get(
                    "/disclosures", params={"thesis_id": "apple-monitor"}
                )
            ).json()
        ) == 1
        assert len(
            (await client.get("/runs", params={"thesis_id": "apple-monitor"})).json()
        ) == 1
        duplicate_accession = await client.post(
            "/disclosures",
            json={
                "document_id": "different-document-id",
                "thesis_id": "apple-monitor",
                "source_id": "0000320193-25-000079",
                "source_date": "2025-08-01",
                "source_url": "https://example.com/changed-copy",
                "content": "<html><body>Changed copy of the same filing.</body></html>",
            },
        )
        assert duplicate_accession.status_code == 409
        invalid_form = await client.put(
            "/theses/apple-monitor/monitor",
            json={"cik": "320193", "forms": ["../../10-K"], "enabled": True},
        )
        assert invalid_form.status_code == 422
        page = (await client.get("/")).text
        assert 'id="monitor-form"' in page
        assert 'id="monitor-sync"' in page
        assert "Daily SEC filing check" in page
    await workflow.close()


async def test_enabled_sec_monitor_polls_and_creates_a_review_run(
    tmp_path: Path,
) -> None:
    bootstrap = DisclosureChunk(
        chunk_id="bootstrap",
        source_id="bootstrap",
        source_date="2024-01-01",
        section="Business",
        text="Cloud demand remained durable.",
        start_char=0,
        end_char=30,
    )

    async def embed(texts: list[str]) -> list[list[float]]:
        return HybridRetriever.deterministic_embeddings(texts)

    async def rerank(query: str, candidates: list[DisclosureChunk]) -> list[str]:
        return [chunk.chunk_id for chunk in candidates]

    retriever = HybridRetriever([bootstrap], embed=embed, rerank=rerank)
    await retriever.index()

    async def analyze(snapshot: ThesisSnapshot, packs: list) -> ThesisDelta:
        return ThesisDelta(
            base_thesis_version=1,
            claim_deltas=[
                ClaimDelta(
                    claim_id="cloud",
                    status=DeltaStatus.SUPPORTED,
                    explanation="The filing supports the claim.",
                    evidence_ids=[packs[0].items[0].evidence_id],
                )
            ],
        )

    class FakeSec:
        def __init__(self) -> None:
            self.checks = 0

        async def filings(
            self, cik: str, after_accession: str | None = None
        ) -> list[dict[str, str]]:
            self.checks += 1
            if self.checks > 2:
                raise RuntimeError("SEC was checked again before the next interval")
            return [
                {
                    "accession": f"0000789019-25-{98 + self.checks:06d}",
                    "filing_date": f"2025-07-{29 + self.checks}",
                    "form": "10-K",
                    "primary_document": "msft-20250630.htm",
                }
            ]

        async def filing_artifacts(self, cik: str, filing: dict[str, str]):
            url = (
                "https://www.sec.gov/Archives/edgar/data/789019/"
                f"{filing['accession'].replace('-', '')}/msft-20250630.htm"
            )
            return [ArtifactInput(
                role="primary_document",
                source_url=url,
                media_type="text/html",
                content=(
                    f"<html><body>Cloud demand remained durable. "
                    f"{filing['accession']}</body></html>"
                ).encode(),
            )], []

    thesis = ThesisSnapshot(
        thesis_id="microsoft-monitor",
        company="Microsoft Corp.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="cloud",
                statement="Cloud demand remains durable.",
                rationale="Cloud supports recurring growth.",
            )
        ],
    )
    workflow = await AgenticThesisWorkflow.create(
        tmp_path / "sec-poll.sqlite", retriever, analyze
    )
    app = create_app(
        workflow,
        sec_client=FakeSec(),
        monitor_interval=0.01,
        collection_interval=1.5,
    )
    await workflow.create_thesis(thesis)
    await workflow.configure_sec_monitor(
        thesis.thesis_id, "0000789019", ["10-K"], True
    )

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with asyncio.timeout(2):
                while not (runs := (await client.get("/runs")).json()):
                    await asyncio.sleep(0)
            assert runs[0]["run_id"] == "sec-microsoft-monitor-0000789019-25-000099"
            events = await client.get(f"/runs/{runs[0]['run_id']}/events")
            assert '"status": "awaiting_review"' in events.text
            await asyncio.sleep(0.03)
            assert len((await client.get("/runs")).json()) == 1
            assert (await client.get("/monitors")).json()[0]["last_error"] is None
            async with asyncio.timeout(2.5):
                while len(runs := (await client.get("/runs")).json()) < 2:
                    await asyncio.sleep(0.01)
            assert {run["run_id"] for run in runs} == {
                "sec-microsoft-monitor-0000789019-25-000099",
                "sec-microsoft-monitor-0000789019-25-000100",
            }
    await workflow.close()


async def test_failed_sec_collection_does_not_count_as_a_success(
    tmp_path: Path,
) -> None:
    async def analyze(snapshot: ThesisSnapshot, packs: list) -> ThesisDelta:
        raise AssertionError("analysis must not run when collection fails")

    class FailingSec:
        async def filings(
            self, cik: str, after_accession: str | None = None
        ) -> list[dict[str, str]]:
            raise TimeoutError("SEC timed out")

    thesis = ThesisSnapshot(
        thesis_id="failed-monitor",
        company="Example Corp.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="durability",
                statement="Demand remains durable.",
                rationale="Recurring customer demand matters.",
            )
        ],
    )
    workflow = await AgenticThesisWorkflow.create(
        tmp_path / "failed-sec.sqlite", object(), analyze
    )
    app = create_app(workflow, sec_client=FailingSec())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/theses", json=thesis.model_dump(mode="json"))
        ).status_code == 201
        assert (
            await client.put(
                "/theses/failed-monitor/monitor",
                json={"cik": "320193", "forms": ["10-K"], "enabled": True},
            )
        ).status_code == 200
        failed = await client.post("/theses/failed-monitor/sync")
        assert failed.status_code == 502
        monitor = (await client.get("/monitors")).json()[0]
        assert monitor["last_checked_at"] is None
        assert monitor["last_error"] == "SEC timed out"
        attempts = (
            await client.get(
                "/collection-attempts", params={"thesis_id": "failed-monitor"}
            )
        ).json()
        assert attempts[0]["status"] == "failed"
        assert attempts[0]["error"] == "SEC timed out"
    await workflow.close()
