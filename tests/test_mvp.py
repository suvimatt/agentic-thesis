import asyncio
import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient

from agentic_thesis.api import create_app
from agentic_thesis.models import (
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
    build_evidence_pack,
    chunk_filing,
    enforce_citations,
    gold_rank,
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

    first = chunk_filing(html, accession="0001", filing_date="2024-09-28", max_chars=20)
    second = chunk_filing(html, accession="0001", filing_date="2024-09-28", max_chars=20)

    assert first == second
    assert first
    assert all(isinstance(chunk, DisclosureChunk) for chunk in first)
    assert first[0].chunk_id.startswith("0001:")
    assert first[0].start_char < first[0].end_char


def test_fixed_sec_filings_exist() -> None:
    filings = files("agentic_thesis").joinpath("sample_data", "filings")
    assert len(filings.joinpath("aapl-2023-10-k.html").read_bytes()) > 1_000_000
    assert len(filings.joinpath("aapl-2024-10-k.html").read_bytes()) > 1_000_000


def test_gold_rank_reports_one_based_position_or_missing() -> None:
    assert gold_rank(["distractor", "gold", "other"], "gold") == 2
    assert gold_rank(["distractor", "other"], "gold") is None


async def test_hybrid_retrieval_reports_measured_recall_at_5() -> None:
    root = Path(__file__).parents[1]
    filing = files("agentic_thesis").joinpath(
        "sample_data", "filings", "aapl-2024-10-k.html"
    ).read_text(errors="ignore")
    chunks = chunk_filing(filing, accession="aapl-2024", filing_date="2024-09-28")
    cases = json.loads((root / "evals/gold.json").read_text())
    gold = {case["query"]: case["gold_chunk_id"] for case in cases}
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    assert all(case["anchor"].lower() in by_id[case["gold_chunk_id"]].text.lower() for case in cases)

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
            query: [hit.chunk.chunk_id for hit in await retriever.search(query, mode=mode, limit=5)]
            for query in gold
        }
        for mode in ("bm25", "vector", "hybrid", "rerank")
    }
    metrics = {mode: recall_at_k(result, gold, 5) for mode, result in results.items()}

    assert metrics == {"bm25": 1.0, "vector": 0.6, "hybrid": 1.0, "rerank": 1.0}
    for case in cases:
        hits = await retriever.search(case["query"], mode="rerank", limit=5)
        pack = build_evidence_pack("gold-eval", case["query"], hits, token_budget=2_000)
        assert f'e:{case["gold_chunk_id"]}' in pack.retained_evidence_ids
        assert pack.tokens_after <= 2_000


def test_evidence_pack_respects_budget_and_rejects_forged_quote() -> None:
    chunks = [
        DisclosureChunk(
            chunk_id="baseline",
            accession="old",
            filing_date="2023-09-30",
            section="Gross Margin",
            text="Services gross margin was 70.8 percent. " + "Baseline detail. " * 80,
            start_char=0,
            end_char=1300,
        ),
        DisclosureChunk(
            chunk_id="new",
            accession="new",
            filing_date="2024-09-28",
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
    assert {item.filing_date for item in pack.items} == {"2023-09-30", "2024-09-28"}
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

    pack.items[1].quote = "A fabricated sentence that never appeared in the filing."
    rejected = enforce_citations(valid, [pack]).claim_deltas[0]
    assert rejected.status == DeltaStatus.UNKNOWN
    assert rejected.evidence_ids == []


async def test_structured_analysis_receives_compressed_quotes_not_source_chunks() -> None:
    chunk = DisclosureChunk(
        chunk_id="new",
        accession="new",
        filing_date="2024-09-28",
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
    assert "Unselected source-only detail" not in prompt
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
    chunks = [
        DisclosureChunk(
            chunk_id="new",
            accession="new",
            filing_date="2024-09-28",
            section="Gross Margin",
            text="Services gross margin was 73.9 percent.",
            start_char=0,
            end_char=40,
        )
    ]

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
    app.state.thesis = thesis
    app.state.chunks = chunks
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/runs", json={"run_id": "shutdown-run"})
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
    chunks = [
        DisclosureChunk(
            chunk_id="new",
            accession="new",
            filing_date="2024-09-28",
            section="Gross Margin",
            text="Services gross margin was 73.9 percent.",
            start_char=0,
            end_char=40,
        )
    ]

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
    paused = await first.start("resume-run", thesis, chunks)
    assert paused["__interrupt__"]
    await first.close()

    restarted = await AgenticThesisWorkflow.create(database, FakeRetriever(), analyze)
    committed = await restarted.resume("resume-run", ReviewDecision(action="approve"))
    assert committed["status"] == "committed"
    assert committed["thesis"].version == 2

    conflict_paused = await restarted.start("conflict-run", committed["thesis"], chunks)
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
        assert "Monitor a thesis" in page.text
        assert "Review thesis changes" in page.text
        assert "Recent runs" in page.text
        assert 'id="runs"' in page.text
        assert "Add a thesis" in page.text
        assert "Add disclosure" in page.text
        assert "Keep current thesis" in page.text
        assert "Apply changes" in page.text
        assert "A stale base version returns HTTP 409" not in page.text
        assert "ThesisSnapshot v1" not in page.text

        started = await client.post(
            "/runs",
            json={
                "run_id": "api-run",
                "thesis": api_thesis.model_dump(mode="json"),
                "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
            },
        )
        assert started.status_code == 202
        assert started.json()["status"] == "running"

        events = await client.get("/runs/api-run/events")
        assert events.headers["content-type"].startswith("text/event-stream")
        assert '"node": "retrieve_claims"' in events.text
        assert '"retrieval_ms": 1.25' in events.text
        assert '"rerank_ms": 2.5' in events.text
        assert '"total_ms":' in events.text
        assert '"tokens_after"' in events.text
        assert '"status": "awaiting_review"' in events.text
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

        stale_thesis = ThesisSnapshot.model_validate(reviewed.json()["thesis"])
        app.state.thesis = api_thesis
        app.state.chunks = chunks
        latest_started = await client.post("/runs", json={"run_id": "api-latest"})
        assert latest_started.status_code == 202
        await client.get("/runs/api-latest/events")
        latest_state = (await client.get("/runs/api-latest")).json()
        assert latest_state["thesis"]["version"] == 2

        conflict_started = await client.post(
            "/runs",
            json={
                "run_id": "api-conflict",
                "thesis": stale_thesis.model_dump(mode="json"),
                "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
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
        error_started = await client.post(
            "/runs",
            json={
                "run_id": "api-error",
                "thesis": error_thesis.model_dump(mode="json"),
                "chunks": [chunk.model_dump(mode="json") for chunk in chunks],
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
    chunk = DisclosureChunk(
        chunk_id="history-evidence",
        accession="history",
        filing_date="2024-09-28",
        section="Gross Margin",
        text="Services gross margin was 73.9 percent.",
        start_char=0,
        end_char=40,
    )

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
        started = await client.post(
            "/runs",
            json={
                "run_id": "history-run",
                "thesis": thesis.model_dump(mode="json"),
                "chunks": [chunk.model_dump(mode="json")],
            },
        )
        assert started.status_code == 202
        events = await client.get("/runs/history-run/events")
        assert "id: 1" in events.text
        assert '"status": "awaiting_review"' in events.text
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
                "base_thesis_version": 1,
                "status": "awaiting_review",
            }
        ]
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
        accession="bootstrap",
        filing_date="2024-01-01",
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
                    "accession": f"{thesis_id}-accession",
                    "filing_date": "2024-09-28",
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
            "/runs", json={"run_id": "missing-run", "thesis_id": "does-not-exist"}
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
            "/runs", json={"run_id": "empty-run", "thesis_id": "no-disclosures"}
        )
        assert no_disclosure_run.status_code == 422

        for thesis_id, expected, excluded in (
            ("apple-custom", "wearables", "cloud"),
            ("microsoft-custom", "cloud", "wearables"),
        ):
            started = await client.post(
                "/runs",
                json={"run_id": f"{thesis_id}-run", "thesis_id": thesis_id},
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
