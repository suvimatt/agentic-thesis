from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from agentic_thesis.models import (
    DisclosureChunk,
    DisclosureDocument,
    EvidencePack,
    ReviewDecision,
    ThesisDelta,
    ThesisSnapshot,
)
from agentic_thesis.rag import HybridRetriever, chunk_filing
from agentic_thesis.workflow import AgenticThesisWorkflow


class AgenticThesisEngine:
    """Stable interface for the AgenticThesis domain workflow."""

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
        initial_chunks: Sequence[DisclosureChunk] = (),
        collection_name: str = "chunks",
    ) -> "AgenticThesisEngine":
        path = Path(data_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        retriever = HybridRetriever(
            list(initial_chunks),
            embed=embed,
            rerank=rerank,
            qdrant_path=path / "qdrant",
            collection_name=collection_name,
        )
        if initial_chunks:
            await retriever.index()
        workflow = await AgenticThesisWorkflow.create(
            path / "agentic_thesis.sqlite", retriever, analyze
        )
        return cls(workflow)

    async def create_thesis(self, thesis: ThesisSnapshot) -> bool:
        return await self._workflow.create_thesis(thesis)

    async def add_disclosure(self, document: DisclosureDocument) -> int | None:
        chunks = chunk_filing(
            document.content,
            accession=document.accession,
            filing_date=document.filing_date,
            source_url=document.source_url,
        )
        if not chunks:
            raise ValueError("disclosure contains no text")
        return (
            len(chunks)
            if await self._workflow.add_disclosure(document, chunks)
            else None
        )

    async def run(self, run_id: str, thesis_id: str) -> dict[str, Any]:
        thesis = await self._workflow.get_thesis(thesis_id)
        if thesis is None:
            raise ValueError("thesis not found")
        chunks = await self._workflow.chunks_for_thesis(thesis_id)
        if not chunks:
            raise ValueError("thesis has no disclosures")
        return await self._workflow.start(run_id, thesis, chunks)

    async def review(
        self, run_id: str, decision: ReviewDecision
    ) -> dict[str, Any]:
        return await self._workflow.resume(run_id, decision)

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._workflow.get(run_id)

    async def close(self) -> None:
        await self._workflow.close()
