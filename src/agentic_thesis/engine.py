import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

from agentic_thesis.models import (
    ArtifactFetchFailure,
    ArtifactInput,
    CollectionAttempt,
    DisclosureChunk,
    DisclosureDocument,
    DisclosureEvent,
    DisclosureSummary,
    EvidencePack,
    IngestionResult,
    ParseStatus,
    RadarEntry,
    ReviewDecision,
    RunStatus,
    RunSummary,
    SecMonitor,
    SourceArtifact,
    SourceAuthority,
    ThesisDelta,
    ThesisRevision,
    ThesisRun,
    ThesisSnapshot,
)
from agentic_thesis.rag import HybridRetriever, canonical_text_from_chunks, chunk_filing
from agentic_thesis.workflow import AgenticThesisWorkflow


class EngineConflictError(ValueError):
    """The requested state transition conflicts with durable engine state."""


class AgenticThesisEngine:
    """Public interface for disclosure-bound thesis revision workflows."""

    def __init__(self, workflow: AgenticThesisWorkflow) -> None:
        self._workflow = workflow

    @classmethod
    async def open_local(
        cls,
        data_dir: str | Path,
        *,
        embed: Callable[[list[str]], Awaitable[list[list[float]]]],
        rerank: Callable[[str, list[DisclosureChunk]], Awaitable[list[str]]],
        analyze: Callable[[ThesisSnapshot, list[EvidencePack]], Awaitable[ThesisDelta]],
        collection_name: str = "chunks",
    ) -> "AgenticThesisEngine":
        path = Path(data_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        retriever = HybridRetriever(
            [],
            embed=embed,
            rerank=rerank,
            qdrant_path=path / "qdrant",
            collection_name=collection_name,
        )
        try:
            workflow = await AgenticThesisWorkflow.create(
                path / "agentic_thesis.sqlite", retriever, analyze
            )
        except Exception:
            retriever.close()
            raise
        return cls(workflow)

    async def create_thesis(self, thesis: ThesisSnapshot) -> ThesisSnapshot:
        if thesis.version != 1:
            raise ValueError("a new thesis must start at version 1")
        if not await self._workflow.create_thesis(thesis):
            raise EngineConflictError("thesis already exists")
        return thesis

    async def get_thesis(self, thesis_id: str) -> ThesisSnapshot | None:
        return await self._workflow.get_thesis(thesis_id)

    async def list_theses(self) -> list[ThesisSnapshot]:
        return await self._workflow.list_theses()

    async def add_disclosure(self, document: DisclosureDocument) -> int:
        if await self.get_thesis(document.thesis_id) is None:
            raise ValueError("thesis not found")
        event = DisclosureEvent(
            event_id=document.event_id or document.document_id,
            thesis_id=document.thesis_id,
            source="manual",
            authority=SourceAuthority.USER_SUPPLIED,
            event_type="manual_disclosure",
            external_id=document.accession,
            filing_date=document.filing_date,
        )
        result = await self._ingest_event(
            event,
            [
                ArtifactInput(
                    role="manual_document",
                    source_url=document.source_url or "urn:agentic-thesis:manual",
                    media_type="text/html",
                    content=document.content.encode(),
                )
            ],
            document_id=document.document_id,
        )
        if not result.chunk_count:
            raise ValueError("disclosure contains no text")
        if not result.disclosure_created:
            raise EngineConflictError("disclosure already exists")
        return result.chunk_count

    async def ingest_event(
        self,
        event: DisclosureEvent,
        artifacts: list[ArtifactInput],
    ) -> IngestionResult:
        if await self.get_thesis(event.thesis_id) is None:
            raise ValueError("thesis not found")
        return await self._ingest_event(event, artifacts, document_id=event.event_id)

    async def _ingest_event(
        self,
        event: DisclosureEvent,
        artifacts: list[ArtifactInput],
        *,
        document_id: str,
    ) -> IngestionResult:
        if not artifacts:
            raise ValueError("event must contain at least one artifact")
        retrieved_at = datetime.now(timezone.utc).isoformat()
        records: list[tuple[SourceArtifact, bytes]] = []
        chunks: list[DisclosureChunk] = []
        artifact_ids: list[str] = []
        primary_content = ""
        primary_url = ""
        offset = 0
        evidence_roles = {
            "primary_document",
            "exhibit",
            "full_submission",
            "manual_document",
            "official_document",
            "presentation",
            "transcript",
        }
        text_media = {"text/html", "text/plain", "application/xhtml+xml", "application/xml", "text/xml"}
        for item in artifacts:
            digest = hashlib.sha256(item.content).hexdigest()
            artifact_id = f"sha256:{digest}"
            artifact_ids.append(artifact_id)
            media_type = item.media_type.split(";", 1)[0].strip().lower()
            parser_name = None
            parser_version = None
            parse_status = ParseStatus.RETAINED
            parse_error = None
            if item.role in evidence_roles and media_type in text_media:
                try:
                    text = item.content.decode("utf-8", errors="replace")
                    parsed = chunk_filing(
                        text,
                        accession=event.external_id,
                        filing_date=event.filing_date,
                        source_url=item.source_url,
                        artifact_id=artifact_id,
                        offset=offset,
                    )
                    if parsed:
                        chunks.extend(parsed)
                        offset = max(chunk.end_char for chunk in parsed) + 1
                        parser_name = "agentic-thesis-structured-text"
                        parser_version = "1"
                        parse_status = ParseStatus.PARSED
                        if item.role == "primary_document" or not primary_content:
                            primary_content = text
                            primary_url = item.source_url
                    else:
                        parse_status = ParseStatus.FAILED
                        parse_error = "artifact contains no complete evidence spans"
                except Exception as exc:
                    parse_status = ParseStatus.FAILED
                    parse_error = str(exc)
            elif item.role in evidence_roles:
                parse_status = ParseStatus.UNSUPPORTED
                parse_error = f"unsupported media type: {media_type}"
            records.append(
                (
                    SourceArtifact(
                        artifact_id=artifact_id,
                        event_id=event.event_id,
                        role=item.role,
                        source_url=item.source_url,
                        media_type=media_type,
                        content_hash=digest,
                        byte_length=len(item.content),
                        retrieved_at=retrieved_at,
                        parser_name=parser_name,
                        parser_version=parser_version,
                        parse_status=parse_status,
                        parse_error=parse_error,
                    ),
                    item.content,
                )
            )
        document = None
        if chunks:
            document = DisclosureDocument(
                document_id=document_id,
                thesis_id=event.thesis_id,
                accession=event.external_id,
                filing_date=event.filing_date,
                source_url=primary_url or chunks[0].source_url,
                content=primary_content or chunks[0].text,
                event_id=event.event_id,
                artifact_ids=list(dict.fromkeys(artifact_ids)),
            )
        event_created, disclosure_created = await self._workflow.add_disclosure(
            document,
            canonical_text_from_chunks(chunks),
            chunks,
            event,
            records,
        )
        return IngestionResult(
            event_id=event.event_id,
            document_id=document.document_id if document else None,
            artifact_ids=list(dict.fromkeys(artifact_ids)),
            chunk_count=len(chunks),
            event_created=event_created,
            disclosure_created=disclosure_created,
        )

    async def get_disclosure(
        self, thesis_id: str, document_id: str
    ) -> DisclosureDocument | None:
        return await self._workflow.get_disclosure(thesis_id, document_id)

    async def list_disclosures(self, thesis_id: str) -> list[DisclosureSummary]:
        return [
            DisclosureSummary.model_validate(item)
            for item in await self._workflow.list_disclosures(thesis_id)
        ]

    async def get_event(self, event_id: str) -> DisclosureEvent | None:
        event = await self._workflow.get_event(event_id)
        return DisclosureEvent.model_validate(event) if event else None

    async def list_artifacts(self, event_id: str) -> list[SourceArtifact]:
        return [
            SourceArtifact.model_validate(item)
            for item in await self._workflow.list_artifacts(event_id)
        ]

    async def get_artifact_content(self, artifact_id: str) -> tuple[bytes, str] | None:
        return await self._workflow.get_artifact_content(artifact_id)

    async def record_artifact_failures(
        self, failures: list[ArtifactFetchFailure]
    ) -> None:
        await self._workflow.record_artifact_failures(failures)

    async def list_artifact_failures(
        self, event_id: str
    ) -> list[ArtifactFetchFailure]:
        return [
            ArtifactFetchFailure.model_validate(item)
            for item in await self._workflow.list_artifact_failures(event_id)
        ]

    async def record_collection_attempt(self, attempt: CollectionAttempt) -> None:
        await self._workflow.record_collection_attempt(attempt)

    async def list_collection_attempts(
        self, thesis_id: str
    ) -> list[CollectionAttempt]:
        return [
            CollectionAttempt.model_validate(item)
            for item in await self._workflow.list_collection_attempts(thesis_id)
        ]

    async def put_radar_entry(self, entry: RadarEntry) -> bool:
        return await self._workflow.put_radar_entry(entry)

    async def list_radar_entries(self, thesis_id: str) -> list[RadarEntry]:
        return [
            RadarEntry.model_validate(item)
            for item in await self._workflow.list_radar_entries(thesis_id)
        ]

    async def start_run(
        self, run_id: str, thesis_id: str, disclosure_id: str
    ) -> RunSummary:
        thesis = await self.get_thesis(thesis_id)
        if thesis is None:
            raise ValueError("thesis not found")
        if await self.get_disclosure(thesis_id, disclosure_id) is None:
            raise ValueError("disclosure not found for thesis")
        if not await self._workflow.register_run(run_id, thesis, disclosure_id):
            raise EngineConflictError("run already exists")
        return RunSummary.model_validate(await self._workflow.get_run(run_id))

    async def execute_run(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        record = await self._workflow.get_run(run_id)
        if record is None:
            raise ValueError("run not found")
        if record["status"] != RunStatus.RUNNING:
            raise EngineConflictError("run is not ready to execute")
        try:
            state = await self._workflow.get(run_id)
            if state:
                updates = self._workflow.stream_resume(run_id)
            else:
                thesis = await self._workflow.get_thesis_version(
                    record["thesis_id"], record["base_thesis_version"]
                )
                chunks = await self._workflow.chunks_for_disclosure(
                    record["thesis_id"], record["disclosure_id"]
                )
                if thesis is None or not chunks:
                    raise RuntimeError("registered run input is missing")
                updates = self._workflow.stream_start(
                    run_id, record["disclosure_id"], thesis, chunks
                )
            async with aclosing(updates):
                async for update in updates:
                    yield update
        except asyncio.CancelledError as exc:
            cleanup = [item for item in exc.args if isinstance(item, asyncio.Task)]
            if cleanup:
                await asyncio.gather(*cleanup, return_exceptions=True)
            raise
        except Exception as exc:
            await self._workflow.record_error(run_id, str(exc))
            raise

    async def run(
        self, run_id: str, thesis_id: str, disclosure_id: str
    ) -> ThesisRun:
        await self.start_run(run_id, thesis_id, disclosure_id)
        async for _ in self.execute_run(run_id):
            pass
        result = await self.get_run(run_id)
        if result is None:
            raise RuntimeError("completed run is missing")
        return result

    async def review(self, run_id: str, decision: ReviewDecision) -> ThesisRun:
        result = await self._workflow.resume(run_id, decision)
        if result.get("status") == "review_conflict":
            raise EngineConflictError(result["error"])
        run = await self.get_run(run_id)
        if run is None:
            raise RuntimeError("reviewed run is missing")
        return run

    async def get_run(self, run_id: str) -> ThesisRun | None:
        record = await self._workflow.get_run(run_id)
        if record is None:
            return None
        state = await self._workflow.get(run_id)
        thesis = await self._workflow.get_thesis_version(
            record["thesis_id"], record["base_thesis_version"]
        )
        if thesis is None:
            raise RuntimeError("run base thesis is missing")
        return ThesisRun.model_validate(
            {
                **record,
                "thesis": thesis,
                "timings_ms": state.get("timings_ms", {}),
                "retrieval_timings_ms": state.get("retrieval_timings_ms", {}),
            }
        )

    async def list_runs(self, thesis_id: str | None = None) -> list[RunSummary]:
        return [
            RunSummary.model_validate(item)
            for item in await self._workflow.list_runs(thesis_id)
        ]

    async def list_revisions(self, thesis_id: str) -> list[ThesisRevision]:
        return [
            ThesisRevision.model_validate(item)
            for item in await self._workflow.list_revisions(thesis_id)
        ]

    async def append_event(self, run_id: str, event: dict[str, Any]) -> int:
        return await self._workflow.append_event(run_id, event)

    async def list_events(
        self, run_id: str, after: int = 0
    ) -> list[tuple[int, dict]]:
        return await self._workflow.list_events(run_id, after)

    async def configure_sec_monitor(
        self, thesis_id: str, cik: str, forms: list[str], enabled: bool
    ) -> SecMonitor:
        if await self.get_thesis(thesis_id) is None:
            raise ValueError("thesis not found")
        return SecMonitor.model_validate(
            await self._workflow.configure_sec_monitor(thesis_id, cik, forms, enabled)
        )

    async def get_sec_monitor(self, thesis_id: str) -> SecMonitor | None:
        monitor = await self._workflow.get_sec_monitor(thesis_id)
        return SecMonitor.model_validate(monitor) if monitor else None

    async def list_sec_monitors(self) -> list[SecMonitor]:
        return [
            SecMonitor.model_validate(item)
            for item in await self._workflow.list_sec_monitors()
        ]

    async def record_sec_sync(
        self,
        thesis_id: str,
        *,
        last_accession: str | None,
        imported: int,
        error: str | None = None,
    ) -> None:
        await self._workflow.record_sec_sync(
            thesis_id,
            last_accession=last_accession,
            imported=imported,
            error=error,
        )

    async def close(self) -> None:
        await self._workflow.close()
