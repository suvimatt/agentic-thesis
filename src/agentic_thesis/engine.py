from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from agentic_thesis.models import (
    DisclosureChunk,
    DisclosureDocument,
    DisclosureSummary,
    EvidencePack,
    ReviewDecision,
    RunStatus,
    RunSummary,
    SecMonitor,
    ThesisDelta,
    ThesisRevision,
    ThesisRun,
    ThesisSnapshot,
)
from agentic_thesis.rag import HybridRetriever, chunk_filing
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
        chunks = chunk_filing(
            document.content,
            accession=document.accession,
            filing_date=document.filing_date,
            source_url=document.source_url,
        )
        if not chunks:
            raise ValueError("disclosure contains no text")
        if not await self._workflow.add_disclosure(document, chunks):
            raise EngineConflictError("disclosure already exists")
        return len(chunks)

    async def get_disclosure(
        self, thesis_id: str, document_id: str
    ) -> DisclosureDocument | None:
        return await self._workflow.get_disclosure(thesis_id, document_id)

    async def list_disclosures(self, thesis_id: str) -> list[DisclosureSummary]:
        return [
            DisclosureSummary.model_validate(item)
            for item in await self._workflow.list_disclosures(thesis_id)
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
            async for update in updates:
                yield update
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
