import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from agentic_thesis import (
    AgenticThesisEngine,
    ArtifactFetchFailure,
    ArtifactInput,
    ClaimDelta,
    DeltaStatus,
    DisclosureDocument,
    DisclosureEvent,
    EngineConflictError,
    ReviewDecision,
    RunStatus,
    SourceAuthority,
    ThesisClaim,
    ThesisDelta,
    ThesisSnapshot,
)
from agentic_thesis.api import create_app
from agentic_thesis.rag import HybridRetriever


@pytest.mark.asyncio
async def test_v1_rejects_a_pre_v1_database_without_modifying_it(tmp_path) -> None:
    database = tmp_path / "agentic_thesis.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 9")
        connection.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")

    async def unused(*args):
        raise AssertionError("model functions must not run")

    with pytest.raises(RuntimeError, match="requires an empty data directory"):
        await AgenticThesisEngine.open_local(
            tmp_path,
            embed=unused,
            rerank=unused,
            analyze=unused,
        )

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'runs'"
        ).fetchone() == ("runs",)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9


@pytest.mark.asyncio
async def test_v1_ingestion_preserves_event_artifacts_and_partial_failures(tmp_path) -> None:
    async def unused(*args):
        raise AssertionError("model functions must not run")

    engine = await AgenticThesisEngine.open_local(
        tmp_path,
        embed=unused,
        rerank=unused,
        analyze=unused,
    )
    thesis = ThesisSnapshot(
        thesis_id="aapl-radar",
        company="Apple Inc.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="demand",
                statement="Demand remains durable.",
                rationale="Demand supports cash generation.",
                falsifiers=["Revenue declines materially."],
            )
        ],
    )
    await engine.create_thesis(thesis)
    event = DisclosureEvent(
        event_id="sec:0000320193-25-000079:aapl",
        thesis_id=thesis.thesis_id,
        source="sec-edgar",
        authority=SourceAuthority.REGULATOR,
        event_type="sec:8-K",
        external_id="0000320193-25-000079",
        filing_date="2025-08-01",
        accepted_at="2025-08-01T16:05:00Z",
        metadata={"form": "8-K", "cik": "0000320193"},
    )
    primary_url = "https://www.sec.gov/example/filing.htm"
    result = await engine.ingest_event(
        event,
        [
            ArtifactInput(
                role="filing_index",
                source_url="https://www.sec.gov/example/filing-index.html",
                media_type="text/html",
                content=b"<html><body>Filing index.</body></html>",
            ),
            ArtifactInput(
                role="primary_document",
                source_url=primary_url,
                media_type="text/html",
                content=b"<html><body>Revenue remained durable.</body></html>",
            ),
            ArtifactInput(
                role="exhibit",
                source_url="https://www.sec.gov/example/exhibit.htm",
                media_type="text/html",
                content=b"<html><body>Services revenue increased.</body></html>",
            ),
            ArtifactInput(
                role="exhibit",
                source_url="https://www.sec.gov/example/slides.pdf",
                media_type="application/pdf",
                content=b"%PDF-1.4 fixture",
            ),
        ],
    )
    assert result.event_created is True
    assert result.disclosure_created is True
    assert result.chunk_count == 2
    assert (await engine.get_event(event.event_id)) == event
    disclosure = await engine.get_disclosure(thesis.thesis_id, result.document_id)
    assert disclosure.event_id == event.event_id
    assert set(disclosure.artifact_ids) == set(result.artifact_ids)
    artifacts = await engine.list_artifacts(event.event_id)
    assert {item.role for item in artifacts} == {
        "filing_index", "primary_document", "exhibit"
    }
    assert any(item.parse_status == "unsupported" for item in artifacts)
    assert any(
        item.role == "primary_document" and item.parse_status == "parsed"
        for item in artifacts
    )
    primary = next(item for item in artifacts if item.role == "primary_document")
    assert await engine.get_artifact_content(primary.artifact_id) == (
        b"<html><body>Revenue remained durable.</body></html>",
        "text/html",
    )
    changed = await engine.ingest_event(
        event,
        [
            ArtifactInput(
                role="primary_document",
                source_url=primary_url,
                media_type="text/html",
                content=b"<html><body>Revenue declined materially.</body></html>",
            )
        ],
    )
    assert changed.event_created is False
    assert changed.disclosure_created is False
    assert len(await engine.list_artifacts(event.event_id)) == 5

    now = datetime.now(timezone.utc).isoformat()
    failure = ArtifactFetchFailure(
        event_id=event.event_id,
        role="exhibit",
        source_url="https://www.sec.gov/example/missing.pdf",
        error="timed out",
        occurred_at=now,
    )
    await engine.record_artifact_failures([failure])
    assert await engine.list_artifact_failures(event.event_id) == [failure]

    with sqlite3.connect(tmp_path / "agentic_thesis.sqlite") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 10
        assert connection.execute("SELECT COUNT(*) FROM source_artifacts").fetchone()[0] == 5
    await engine.close()


@pytest.mark.asyncio
async def test_public_engine_runs_local_thesis_lifecycle(tmp_path) -> None:
    thesis = ThesisSnapshot(
        thesis_id="aapl-primary",
        company="Apple Inc.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="services-margin",
                statement="Services mix supports margins.",
                rationale="Services has higher margins.",
                falsifiers=["Services margin declines."],
            )
        ],
    )
    old_disclosure = DisclosureDocument(
        document_id="aapl-2023",
        thesis_id=thesis.thesis_id,
        accession="aapl-2023",
        filing_date="2023-09-30",
        source_url="https://example.com/aapl-2023",
        content="<p>Old filing: Services gross margin was 70.8 percent.</p>",
    )
    disclosure = DisclosureDocument(
        document_id="aapl-2024",
        thesis_id=thesis.thesis_id,
        accession="aapl-2024",
        filing_date="2024-09-28",
        source_url="https://example.com/aapl-2024",
        content="<h1>Gross Margin</h1><p>Services gross margin was 73.9 percent.</p>",
    )

    embedded_texts: list[str] = []

    async def embed(texts: list[str]) -> list[list[float]]:
        embedded_texts.extend(texts)
        return HybridRetriever.deterministic_embeddings(texts)

    async def rerank(query, candidates):
        return [candidate.chunk_id for candidate in candidates]

    async def analyze(snapshot, packs):
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

    engine = await AgenticThesisEngine.open_local(
        tmp_path,
        embed=embed,
        rerank=rerank,
        analyze=analyze,
    )
    assert await engine.create_thesis(thesis) == thesis
    assert await engine.add_disclosure(old_disclosure) == 1
    assert await engine.add_disclosure(disclosure) == 1

    paused = await engine.run(
        "aapl-2024-review", thesis.thesis_id, disclosure.document_id
    )
    assert paused.status == RunStatus.AWAITING_REVIEW
    assert paused.disclosure_id == disclosure.document_id
    assert {
        item.accession
        for pack in paused.evidence_packs
        for item in pack.items
    } == {"aapl-2024"}
    evidence = paused.evidence_packs[0].items[0]
    assert evidence.kind == "sentence"
    assert evidence.artifact_id.startswith("sha256:")
    assert evidence.quote == "Services gross margin was 73.9 percent."
    assert evidence.source_text[
        evidence.start_char - evidence.source_start_char:
        evidence.end_char - evidence.source_start_char
    ] == evidence.quote
    assert any("Services margin declines" in text for text in embedded_texts)
    with sqlite3.connect(tmp_path / "agentic_thesis.sqlite") as connection:
        canonical_text = connection.execute(
            "SELECT canonical_text FROM disclosures WHERE document_id = ?",
            (disclosure.document_id,),
        ).fetchone()[0]
    assert canonical_text[evidence.start_char:evidence.end_char] == evidence.quote
    with pytest.raises(EngineConflictError, match="run already exists"):
        await engine.start_run(
            "aapl-2024-review", thesis.thesis_id, disclosure.document_id
        )
    other_thesis = thesis.model_copy(update={"thesis_id": "msft-primary"})
    await engine.create_thesis(other_thesis)
    with pytest.raises(ValueError, match="disclosure not found for thesis"):
        await engine.start_run(
            "wrong-thesis", other_thesis.thesis_id, disclosure.document_id
        )
    other_disclosure = disclosure.model_copy(
        update={
            "document_id": "msft-2024",
            "thesis_id": other_thesis.thesis_id,
            "accession": "msft-2024",
        }
    )
    await engine.add_disclosure(other_disclosure)
    await engine.run("concurrent-a", other_thesis.thesis_id, other_disclosure.document_id)
    await engine.run("concurrent-b", other_thesis.thesis_id, other_disclosure.document_id)
    concurrent = await asyncio.gather(
        engine.review("concurrent-a", ReviewDecision(action="approve")),
        engine.review("concurrent-b", ReviewDecision(action="approve")),
    )
    assert {run.status for run in concurrent} == {
        RunStatus.COMMITTED,
        RunStatus.VERSION_CONFLICT,
    }
    assert (await engine.get_thesis(other_thesis.thesis_id)).version == 2
    assert len(await engine.list_revisions(other_thesis.thesis_id)) == 1

    committed = await engine.review(
        "aapl-2024-review", ReviewDecision(action="approve")
    )
    assert committed.status == RunStatus.COMMITTED
    assert committed.committed_thesis_version == 2
    assert (await engine.get_thesis(thesis.thesis_id)).version == 2
    assert (await engine.get_run("aapl-2024-review")).status == RunStatus.COMMITTED
    revisions = await engine.list_revisions(thesis.thesis_id)
    assert len(revisions) == 1
    assert revisions[0].disclosure_id == disclosure.document_id
    assert revisions[0].review.action == "approve"
    assert revisions[0].delta.claim_deltas[0].status == DeltaStatus.SUPPORTED

    rejected = await engine.run(
        "aapl-2024-rejected", thesis.thesis_id, disclosure.document_id
    )
    rejected = await engine.review(
        rejected.run_id, ReviewDecision(action="reject")
    )
    assert rejected.status == RunStatus.REJECTED
    assert rejected.delta is not None
    assert rejected.evidence_packs
    assert rejected.review == ReviewDecision(action="reject")
    assert rejected.committed_thesis_version is None
    assert len(await engine.list_revisions(thesis.thesis_id)) == 1
    assert (await engine.get_thesis(thesis.thesis_id)).version == 2

    await engine.append_event(
        committed.run_id, {"node": "late-observer", "status": "running"}
    )
    assert (await engine.get_run(committed.run_id)).status == RunStatus.COMMITTED

    app = create_app(engine)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/theses/{thesis.thesis_id}")
            assert response.status_code == 200
            assert response.json()["version"] == 2
            revisions_response = await client.get(
                f"/theses/{thesis.thesis_id}/revisions"
            )
            assert revisions_response.status_code == 200
            assert revisions_response.json()[0]["committed_thesis_version"] == 2

    await engine.close()
    restarted = await AgenticThesisEngine.open_local(
        tmp_path,
        embed=embed,
        rerank=rerank,
        analyze=analyze,
    )
    durable_commit = await restarted.get_run(committed.run_id)
    assert durable_commit.delta == committed.delta
    assert durable_commit.evidence_packs == committed.evidence_packs
    assert durable_commit.review == committed.review
    assert durable_commit.committed_thesis_version == 2
    durable_rejection = await restarted.get_run(rejected.run_id)
    assert durable_rejection.status == RunStatus.REJECTED
    assert durable_rejection.review == ReviewDecision(action="reject")
    await restarted.close()
