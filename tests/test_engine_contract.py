import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentic_thesis import (
    AgenticThesisEngine,
    ArtifactFetchFailure,
    ArtifactInput,
    ClaimDelta,
    DeltaStatus,
    DisclosureChunk,
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
from agentic_thesis.api import OfficialIrClient, create_app
from agentic_thesis.rag import HybridRetriever


def _text_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(result)


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
        event_date="2025-08-01",
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
    assert any(
        item.parse_status == "failed" and "malformed PDF" in item.parse_error
        for item in artifacts
    )
    assert any(
        item.role == "primary_document" and item.parse_status == "parsed"
        for item in artifacts
    )
    primary = next(item for item in artifacts if item.role == "primary_document")
    assert await engine.get_artifact_content(primary.artifact_id) == (
        b"<html><body>Revenue remained durable.</body></html>"
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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 11
        assert connection.execute("SELECT COUNT(*) FROM source_artifacts").fetchone()[0] == 5
    await engine.close()


@pytest.mark.asyncio
async def test_event_processing_is_replay_safe_and_pdf_citations_keep_pages(tmp_path) -> None:
    async def embed(texts: list[str]) -> list[list[float]]:
        return HybridRetriever.deterministic_embeddings(texts)

    async def rerank(query, candidates):
        return [candidate.chunk_id for candidate in candidates]

    async def analyze(snapshot, packs):
        assert packs[0].items[0].page_number == 1
        return ThesisDelta(
            base_thesis_version=snapshot.version,
            claim_deltas=[
                ClaimDelta(
                    claim_id="revenue",
                    status=DeltaStatus.POSSIBLY_INVALIDATED,
                    explanation="Revenue declined materially.",
                    evidence_ids=[packs[0].items[0].evidence_id],
                    matched_falsifier="Revenue declines materially.",
                )
            ],
        )

    engine = await AgenticThesisEngine.open_local(
        tmp_path, embed=embed, rerank=rerank, analyze=analyze
    )
    await engine.create_thesis(
        ThesisSnapshot(
            thesis_id="issuer-radar",
            company="Example Inc.",
            version=1,
            claims=[
                ThesisClaim(
                    claim_id="revenue",
                    statement="Revenue remains durable.",
                    rationale="Revenue funds reinvestment.",
                    falsifiers=["Revenue declines materially."],
                )
            ],
        )
    )
    event = DisclosureEvent(
        event_id="ir:results:2026-q2",
        thesis_id="issuer-radar",
        source="issuer-ir",
        authority=SourceAuthority.ISSUER,
        event_type="ir:official_document",
        external_id="https://issuer.example/results-q2.pdf#v1",
        event_date="2026-08-01",
    )
    artifact = ArtifactInput(
        role="official_document",
        source_url="https://issuer.example/results-q2.pdf",
        media_type="application/pdf",
        content=_text_pdf("Revenue declines materially."),
    )
    first = await engine.process_event(event, [artifact], run_id="ir-results-q2")
    second = await engine.process_event(event, [artifact], run_id="ir-results-q2")
    duplicate_event = event.model_copy(
        update={
            "event_id": "ir:results:duplicate-release",
            "external_id": "https://issuer.example/duplicate.pdf#v1",
        }
    )
    duplicate = await engine.process_event(
        duplicate_event, [artifact], run_id="ir-results-duplicate"
    )
    assert first.radar_outcome == "needs_review"
    assert first.run_id == second.run_id == "ir-results-q2"
    assert duplicate.radar_outcome == "ignored"
    assert await engine.get_event(duplicate_event.event_id) == duplicate_event
    assert len(await engine.list_radar_entries("issuer-radar")) == 2
    assert len(await engine.list_runs("issuer-radar")) == 1
    updates = [update async for update in engine.execute_run("ir-results-q2")]
    assert updates[-1].get("__interrupt__")
    stored = await engine.list_artifacts(event.event_id)
    assert stored[0].parser_name == "pypdf"
    assert stored[0].parse_status == "parsed"
    await engine.close()


@pytest.mark.asyncio
async def test_atomic_duplicate_routing_preserves_each_source_observation(tmp_path) -> None:
    async def unused(*args):
        raise AssertionError("model functions must not run")

    engine = await AgenticThesisEngine.open_local(
        tmp_path, embed=unused, rerank=unused, analyze=unused
    )
    await engine.create_thesis(
        ThesisSnapshot(
            thesis_id="atomic-radar",
            company="Example Inc.",
            version=1,
            claims=[
                ThesisClaim(
                    claim_id="revenue",
                    statement="Revenue remains durable.",
                    rationale="Revenue matters.",
                    falsifiers=["Revenue declines materially."],
                )
            ],
        )
    )
    events = [
        DisclosureEvent(
            event_id=f"issuer:event:{index}",
            thesis_id="atomic-radar",
            source="issuer-ir",
            authority=SourceAuthority.ISSUER,
            event_type="ir:official_document",
            external_id=f"issuer-event-{index}",
            event_date="2026-08-01",
        )
        for index in (1, 2)
    ]
    content = b"<p>Revenue declines materially.</p>"
    results = await asyncio.gather(
        engine.process_event(
            events[0],
            [
                ArtifactInput(
                    role="official_document",
                    source_url="https://issuer.example/results.html",
                    media_type="text/html",
                    content=content,
                )
            ],
            run_id="atomic-run-1",
        ),
        engine.process_event(
            events[1],
            [
                ArtifactInput(
                    role="official_document",
                    source_url="https://issuer.example/results.txt",
                    media_type="text/plain",
                    content=content,
                )
            ],
            run_id="atomic-run-2",
        ),
    )
    assert {result.radar_outcome for result in results} == {
        "needs_review",
        "ignored",
    }
    assert sum(result.run_id is not None for result in results) == 1
    assert all(result.event_created and result.disclosure_created for result in results)
    radar = await engine.list_radar_entries("atomic-radar")
    ignored = next(entry for entry in radar if entry.outcome == "ignored")
    assert ignored.reason_codes == ["exact_duplicate"]
    assert ignored.run_id is None
    assert {
        (await engine.list_artifacts(event.event_id))[0].media_type
        for event in events
    } == {"text/html", "text/plain"}
    assert len(await engine.list_runs("atomic-radar")) == 1
    replayed = await asyncio.gather(
        *[
            engine.process_event(
                event,
                [
                    ArtifactInput(
                        role="official_document",
                        source_url=f"https://issuer.example/results.{suffix}",
                        media_type=media_type,
                        content=content,
                    )
                ],
                run_id=f"atomic-run-{index}",
            )
            for index, (event, suffix, media_type) in enumerate(
                zip(events, ("html", "txt"), ("text/html", "text/plain")), 1
            )
        ]
    )
    assert {
        result.event_id: (result.radar_outcome, result.run_id)
        for result in replayed
    } == {
        result.event_id: (result.radar_outcome, result.run_id)
        for result in results
    }
    assert len(await engine.list_runs("atomic-radar")) == 1

    secondary = await engine.process_event(
        DisclosureEvent(
            event_id="news:event:1",
            thesis_id="atomic-radar",
            source="news",
            authority=SourceAuthority.SECONDARY,
            event_type="news:article",
            external_id="news-event-1",
            event_date="2026-08-02",
        ),
        [
            ArtifactInput(
                role="official_document",
                source_url="https://news.example/article",
                media_type="text/plain",
                content=b"Revenue declines materially according to the report.",
            )
        ],
        run_id="secondary-must-not-run",
    )
    assert secondary.radar_outcome == "digest"
    assert secondary.run_id is None
    assert len(await engine.list_runs("atomic-radar")) == 1

    with sqlite3.connect(tmp_path / "agentic_thesis.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_artifacts").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM event_artifacts").fetchone()[0] == 3
    await engine.close()


@pytest.mark.asyncio
async def test_image_only_pdf_uses_bounded_opt_in_ocr(tmp_path) -> None:
    async def unused(*args):
        raise AssertionError("model functions must not run")

    async def ocr_pdf(content: bytes, max_pages: int) -> list[str]:
        assert max_pages == 1
        return ["Revenue declines materially."]

    engine = await AgenticThesisEngine.open_local(
        tmp_path,
        embed=unused,
        rerank=unused,
        analyze=unused,
        ocr_pdf=ocr_pdf,
        ocr_max_pages=1,
    )
    await engine.create_thesis(
        ThesisSnapshot(
            thesis_id="ocr",
            company="Example Inc.",
            version=1,
            claims=[
                ThesisClaim(
                    claim_id="revenue",
                    statement="Revenue remains durable.",
                    rationale="Revenue matters.",
                )
            ],
        )
    )
    event = DisclosureEvent(
        event_id="ir:scan",
        thesis_id="ocr",
        source="issuer-ir",
        authority=SourceAuthority.ISSUER,
        event_type="ir:official_document",
        external_id="scan-v1",
        event_date="2026-08-01",
    )
    result = await engine.ingest_event(
        event,
        [
            ArtifactInput(
                role="official_document",
                source_url="https://issuer.example/scan.pdf",
                media_type="application/pdf",
                content=_text_pdf(""),
            )
        ],
    )
    assert result.chunk_count == 1
    stored = await engine.list_artifacts(event.event_id)
    assert stored[0].parser_name == "configured-ocr"
    assert stored[0].parse_status == "parsed"
    await engine.close()


@pytest.mark.asyncio
async def test_official_ir_monitor_detects_new_replaced_and_removed_documents(tmp_path) -> None:
    async def embed(texts: list[str]) -> list[list[float]]:
        return HybridRetriever.deterministic_embeddings(texts)

    async def rerank(query, candidates):
        return [candidate.chunk_id for candidate in candidates]

    async def analyze(snapshot, packs):
        return ThesisDelta(
            base_thesis_version=snapshot.version,
            claim_deltas=[
                ClaimDelta(
                    claim_id="cloud",
                    status=DeltaStatus.SUPPORTED,
                    explanation="Cloud demand remains durable.",
                    evidence_ids=[packs[0].items[0].evidence_id],
                )
            ],
        )

    class FakeIr:
        discover = staticmethod(OfficialIrClient.discover)

        def __init__(self) -> None:
            self.page = b'<a href="/earnings-q2.html">Q2 earnings results</a>'
            self.document = b"<html><body>Cloud demand remains durable.</body></html>"

        async def read(self, url: str) -> tuple[bytes, str]:
            if url.endswith("earnings-q2.html"):
                return self.document, "text/html"
            return self.page, "text/html"

    engine = await AgenticThesisEngine.open_local(
        tmp_path, embed=embed, rerank=rerank, analyze=analyze
    )
    await engine.create_thesis(
        ThesisSnapshot(
            thesis_id="official-ir",
            company="Example Inc.",
            version=1,
            claims=[
                ThesisClaim(
                    claim_id="cloud",
                    statement="Cloud demand remains durable.",
                    rationale="Cloud funds growth.",
                )
            ],
        )
    )
    fake = FakeIr()
    app = create_app(engine, ir_client=fake)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        configured = await client.put(
            "/theses/official-ir/ir-monitor",
            json={"urls": ["https://issuer.example/investors"], "enabled": True},
        )
        assert configured.status_code == 200
        for invalid_url in (
            "http://issuer.example/investors",
            "https://localhost/investors",
            "https://10.0.0.1/investors",
            "https://[::1]/investors",
            "https://user:password@issuer.example/investors",
        ):
            invalid = await client.put(
                "/theses/official-ir/ir-monitor",
                json={"urls": [invalid_url], "enabled": True},
            )
            assert invalid.status_code == 422, invalid_url
        first = await client.post("/theses/official-ir/ir-sync")
        assert first.status_code == 200
        assert first.json()["imported"] == 1
        run_id = first.json()["run_ids"][0]
        await app.state.run_tasks[run_id]
        radar = (await client.get("/radar", params={"thesis_id": "official-ir"})).json()
        assert radar[0]["outcome"] == "needs_review"
        event_id = radar[0]["event_id"]
        artifacts = (await client.get(f"/events/{event_id}/artifacts")).json()
        assert {item["role"] for item in artifacts} == {
            "discovery_page", "official_document"
        }
        download = await client.get(f"/artifacts/{artifacts[0]['artifact_id']}")
        assert download.headers["content-type"] == "application/octet-stream"
        assert download.headers["x-content-type-options"] == "nosniff"
        assert download.headers["content-disposition"].startswith("attachment;")

        unchanged = await client.post("/theses/official-ir/ir-sync")
        assert unchanged.json()["imported"] == 0
        fake.document = b"<html><body>Cloud demand remains durable. Revenue expanded.</body></html>"
        replaced = await client.post("/theses/official-ir/ir-sync")
        assert replaced.json()["imported"] == 1
        fake.page = b"<html><body>No current document.</body></html>"
        removed = await client.post("/theses/official-ir/ir-sync")
        assert removed.json()["imported"] == 1
        events = (await client.get("/radar", params={"thesis_id": "official-ir"})).json()
        event_types = []
        for item in events:
            event_types.append(
                (await client.get(f"/events/{item['event_id']}")).json()["event_type"]
            )
        assert "ir:link_removed" in event_types
    await engine.close()


def test_official_ir_atom_discovery_keeps_relevant_same_host_links() -> None:
    feed = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Quarterly earnings results</title>
        <link href="https://issuer.example/reports/q2.pdf" />
        <published>2026-08-01T12:00:00Z</published>
      </entry>
      <entry>
        <title>Quarterly earnings results mirror</title>
        <link href="https://cdn.example/q2.pdf" />
      </entry>
    </feed>"""
    assert OfficialIrClient.discover(
        "https://issuer.example/investors/feed.xml",
        feed,
        "application/atom+xml",
    ) == [
        (
            "https://issuer.example/reports/q2.pdf",
            "Quarterly earnings results",
            "2026-08-01",
        )
    ]


def test_official_ir_fetch_rejects_a_hostname_resolving_to_private_ip(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "agentic_thesis.api.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="non-public"):
        OfficialIrClient()._read("https://issuer.example/investors")


@pytest.mark.asyncio
async def test_sec_monitor_links_amendment_to_original_filing(tmp_path) -> None:
    async def embed(texts: list[str]) -> list[list[float]]:
        return HybridRetriever.deterministic_embeddings(texts)

    async def rerank(query, candidates):
        return [candidate.chunk_id for candidate in candidates]

    async def analyze(snapshot, packs):
        return ThesisDelta(
            base_thesis_version=snapshot.version,
            claim_deltas=[
                ClaimDelta(
                    claim_id="revenue",
                    status=DeltaStatus.SUPPORTED,
                    explanation="Revenue remains durable.",
                    evidence_ids=[packs[0].items[0].evidence_id],
                )
            ],
        )

    original = {
        "accession": "0000000001-26-000001",
        "filing_date": "2026-02-01",
        "form": "10-K",
        "primary_document": "annual.htm",
        "report_date": "2025-12-31",
    }
    amendment = {
        "accession": "0000000001-26-000002",
        "filing_date": "2026-02-02",
        "form": "10-K/A",
        "primary_document": "annual-amendment.htm",
        "report_date": "2025-12-31",
    }

    class FakeSec:
        def __init__(self) -> None:
            self.calls = 0

        async def filings(self, cik, after_accession=None):
            self.calls += 1
            return [original] if self.calls == 1 else [amendment, original]

        async def filing_artifacts(self, cik, filing):
            content = (
                "<html><body>Revenue remains durable. "
                f"{filing['accession']}.</body></html>"
            ).encode()
            return [
                ArtifactInput(
                    role="primary_document",
                    source_url=f"https://www.sec.gov/{filing['primary_document']}",
                    media_type="text/html",
                    content=content,
                )
            ], []

    engine = await AgenticThesisEngine.open_local(
        tmp_path, embed=embed, rerank=rerank, analyze=analyze
    )
    await engine.create_thesis(
        ThesisSnapshot(
            thesis_id="amendment",
            company="Example Inc.",
            version=1,
            claims=[
                ThesisClaim(
                    claim_id="revenue",
                    statement="Revenue remains durable.",
                    rationale="Revenue matters.",
                )
            ],
        )
    )
    app = create_app(engine, sec_client=FakeSec())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        configured = await client.put(
            "/theses/amendment/monitor",
            json={"cik": "1", "forms": ["10-K"], "enabled": True},
        )
        assert configured.status_code == 200
        first = await client.post("/theses/amendment/sync")
        await app.state.run_tasks[first.json()["run_ids"][0]]
        second = await client.post("/theses/amendment/sync")
        await app.state.run_tasks[second.json()["run_ids"][0]]
        radar = (await client.get("/radar", params={"thesis_id": "amendment"})).json()
        events = [
            (await client.get(f"/events/{entry['event_id']}")).json()
            for entry in radar
        ]
        amended = next(event for event in events if event["metadata"]["is_amendment"] == "true")
        original_event = next(event for event in events if event["metadata"]["is_amendment"] == "false")
        assert amended["amended_event_id"] == original_event["event_id"]
    await engine.close()


def test_versioned_radar_gold_policy() -> None:
    gold = json.loads(
        (Path(__file__).parents[1] / "evals" / "radar_gold.json").read_text()
    )
    thesis = ThesisSnapshot(
        thesis_id="radar-gold",
        company="Example Inc.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="revenue",
                statement="Revenue remains durable.",
                rationale="Revenue funds reinvestment.",
                falsifiers=["Revenue declines materially."],
            )
        ],
    )
    for case in gold["cases"]:
        chunks = (
            [
                DisclosureChunk(
                    chunk_id=case["case_id"],
                    source_id=case["case_id"],
                    source_date="2026-08-01",
                    section="Unknown",
                    text=case["text"],
                    start_char=0,
                    end_char=len(case["text"]),
                )
            ]
            if case["text"]
            else []
        )
        outcome, reasons, _, _ = AgenticThesisEngine._route_event(
            thesis,
            DisclosureEvent(
                event_id=case["case_id"],
                thesis_id=thesis.thesis_id,
                source="fixture",
                authority=case["authority"],
                event_type="fixture",
                external_id=case["case_id"],
                event_date="2026-08-01",
                metadata={"form_family": case["form_family"]},
            ),
            chunks,
        )
        assert outcome == case["expected_outcome"], case["case_id"]
        assert case["expected_reason"] in reasons, case["case_id"]


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
        source_id="aapl-2023",
        source_date="2023-09-30",
        source_url="https://example.com/aapl-2023",
        content="<p>Old filing: Services gross margin was 70.8 percent.</p>",
    )
    disclosure = DisclosureDocument(
        document_id="aapl-2024",
        thesis_id=thesis.thesis_id,
        source_id="aapl-2024",
        source_date="2024-09-28",
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
        item.source_id
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
            "source_id": "msft-2024",
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
