import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from time import perf_counter
from typing import Any

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from agentic_thesis.models import (
    DisclosureChunk,
    ResearchState,
    ReviewDecision,
    ThesisDelta,
    ThesisSnapshot,
)
from agentic_thesis.rag import RetrievalHit, build_evidence_pack, enforce_citations


class AgenticThesisWorkflow:
    def __init__(
        self,
        connection: aiosqlite.Connection,
        checkpointer: AsyncSqliteSaver,
        retriever: Any,
        analyze: Callable[[ThesisSnapshot, list], Awaitable[ThesisDelta]],
    ) -> None:
        self.connection = connection
        self.checkpointer = checkpointer
        self.retriever = retriever
        self.analyze = analyze
        self.model_calls = asyncio.Semaphore(3)
        builder = StateGraph(ResearchState)
        builder.add_node("retrieve_claims", self._retrieve_claims)
        builder.add_node("build_evidence_packs", self._build_evidence_packs)
        builder.add_node("analyze_deltas", self._analyze_deltas)
        builder.add_node("validate_citations", self._validate_citations)
        builder.add_node("human_review", self._human_review)
        builder.add_node("commit_snapshot", self._commit_snapshot)
        builder.set_entry_point("retrieve_claims")
        builder.add_edge("retrieve_claims", "build_evidence_packs")
        builder.add_edge("build_evidence_packs", "analyze_deltas")
        builder.add_edge("analyze_deltas", "validate_citations")
        builder.add_edge("validate_citations", "human_review")
        builder.add_edge("human_review", "commit_snapshot")
        builder.add_edge("commit_snapshot", END)
        self.graph = builder.compile(checkpointer=checkpointer)

    @classmethod
    async def create(
        cls,
        database: str | Path,
        retriever: Any,
        analyze: Callable[[ThesisSnapshot, list], Awaitable[ThesisDelta]],
    ) -> "AgenticThesisWorkflow":
        connection = await aiosqlite.connect(str(database))
        checkpointer = AsyncSqliteSaver(connection)
        await checkpointer.setup()
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS thesis_heads (
                thesis_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS thesis_snapshots (
                thesis_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL,
                PRIMARY KEY (thesis_id, version)
            );
            """
        )
        await connection.commit()
        return cls(connection, checkpointer, retriever, analyze)

    async def _retrieve_claims(self, state: ResearchState) -> dict[str, Any]:
        started = perf_counter()
        results = await asyncio.gather(
            *[self._search(claim.statement) for claim in state.thesis.claims]
        )
        return {
            "retrieved": {
                claim.claim_id: [hit.chunk.chunk_id for hit in hits]
                for claim, hits in zip(state.thesis.claims, results, strict=True)
            },
            "timings_ms": self._timings(state, "retrieve_claims", started),
        }

    @staticmethod
    def _timings(state: ResearchState, node: str, started: float) -> dict[str, float]:
        return {**state.timings_ms, node: round((perf_counter() - started) * 1_000, 3)}

    async def _search(self, query: str) -> list[RetrievalHit]:
        async with self.model_calls, asyncio.timeout(45):
            return await self.retriever.search(query, mode="rerank", limit=6)

    async def _build_evidence_packs(self, state: ResearchState) -> dict[str, Any]:
        started = perf_counter()
        chunks = {chunk.chunk_id: chunk for chunk in state.chunks}
        packs = []
        for claim in state.thesis.claims:
            ids = state.retrieved[claim.claim_id]
            hits = [
                RetrievalHit(chunks[chunk_id], float(len(ids) - rank))
                for rank, chunk_id in enumerate(ids)
            ]
            packs.append(
                build_evidence_pack(
                    claim.claim_id,
                    claim.statement,
                    hits,
                    token_budget=2_000,
                )
            )
        return {
            "evidence_packs": packs,
            "timings_ms": self._timings(state, "build_evidence_packs", started),
        }

    async def _analyze_deltas(self, state: ResearchState) -> dict[str, Any]:
        started = perf_counter()
        async with self.model_calls, asyncio.timeout(60):
            delta = await self.analyze(state.thesis, state.evidence_packs)
        return {
            "delta": delta,
            "timings_ms": self._timings(state, "analyze_deltas", started),
        }

    async def _validate_citations(self, state: ResearchState) -> dict[str, Any]:
        started = perf_counter()
        return {
            "delta": enforce_citations(state.delta, state.evidence_packs, state.thesis),
            "timings_ms": self._timings(state, "validate_citations", started),
        }

    async def _human_review(self, state: ResearchState) -> dict[str, Any]:
        started = perf_counter()
        decision = interrupt(
            {
                "run_id": state.run_id,
                "delta": state.delta.model_dump(mode="json"),
                "message": "Review the proposed thesis changes.",
            }
        )
        return {
            "review": ReviewDecision.model_validate(decision),
            "timings_ms": self._timings(state, "human_review", started),
        }

    async def _commit_snapshot(self, state: ResearchState) -> dict[str, Any]:
        started = perf_counter()
        if state.review.action == "reject":
            return {
                "status": "rejected",
                "timings_ms": self._timings(state, "commit_snapshot", started),
            }
        delta = enforce_citations(
            state.review.edited_delta or state.delta,
            state.evidence_packs,
            state.thesis,
        )
        expected_claims = {claim.claim_id for claim in state.thesis.claims}
        supplied_claims = [item.claim_id for item in delta.claim_deltas]
        if (
            delta.base_thesis_version != state.thesis.version
            or len(supplied_claims) != len(set(supplied_claims))
            or set(supplied_claims) != expected_claims
        ):
            return {
                "status": "invalid_review",
                "error": "review must contain exactly one delta per current claim",
                "timings_ms": self._timings(state, "commit_snapshot", started),
            }
        new_claims = [
            claim.model_copy(
                update={
                    "evidence_refs": sorted(
                        set(claim.evidence_refs)
                        | set(
                            next(
                                item.evidence_ids
                                for item in delta.claim_deltas
                                if item.claim_id == claim.claim_id
                            )
                        )
                    )
                }
            )
            for claim in state.thesis.claims
        ]
        snapshot = state.thesis.model_copy(
            deep=True,
            update={"version": state.thesis.version + 1, "claims": new_claims},
        )
        cursor = await self.connection.execute(
            "UPDATE thesis_heads SET version = ? WHERE thesis_id = ? AND version = ?",
            (snapshot.version, snapshot.thesis_id, state.thesis.version),
        )
        if cursor.rowcount != 1:
            await self.connection.rollback()
            return {
                "status": "version_conflict",
                "error": "base thesis version is stale",
                "timings_ms": self._timings(state, "commit_snapshot", started),
            }
        await self.connection.execute(
            "INSERT INTO thesis_snapshots VALUES (?, ?, ?)",
            (snapshot.thesis_id, snapshot.version, snapshot.model_dump_json()),
        )
        await self.connection.commit()
        return {
            "status": "committed",
            "thesis": snapshot,
            "timings_ms": self._timings(state, "commit_snapshot", started),
        }

    async def start(
        self,
        run_id: str,
        thesis: ThesisSnapshot,
        chunks: list[DisclosureChunk],
    ) -> dict[str, Any]:
        state = await self._initialize(run_id, thesis, chunks)
        return await self.graph.ainvoke(state, {"configurable": {"thread_id": run_id}})

    async def current_snapshot(self, initial: ThesisSnapshot) -> ThesisSnapshot:
        cursor = await self.connection.execute(
            """
            SELECT snapshots.snapshot_json
            FROM thesis_heads AS heads
            LEFT JOIN thesis_snapshots AS snapshots
              ON snapshots.thesis_id = heads.thesis_id
             AND snapshots.version = heads.version
            WHERE heads.thesis_id = ?
            """,
            (initial.thesis_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return initial
        if row[0] is None:
            raise RuntimeError("current thesis snapshot is missing")
        return ThesisSnapshot.model_validate_json(row[0])

    async def stream_start(
        self,
        run_id: str,
        thesis: ThesisSnapshot,
        chunks: list[DisclosureChunk],
    ) -> AsyncIterator[dict[str, Any]]:
        state = await self._initialize(run_id, thesis, chunks)
        async for update in self.graph.astream(
            state,
            {"configurable": {"thread_id": run_id}},
            stream_mode="updates",
        ):
            yield update

    async def _initialize(
        self,
        run_id: str,
        thesis: ThesisSnapshot,
        chunks: list[DisclosureChunk],
    ) -> ResearchState:
        await self.connection.execute(
            "INSERT OR IGNORE INTO thesis_heads VALUES (?, ?)",
            (thesis.thesis_id, thesis.version),
        )
        await self.connection.execute(
            "INSERT OR IGNORE INTO thesis_snapshots VALUES (?, ?, ?)",
            (thesis.thesis_id, thesis.version, thesis.model_dump_json()),
        )
        await self.connection.commit()
        return ResearchState(run_id=run_id, thesis=thesis, chunks=chunks)

    async def resume(self, run_id: str, decision: ReviewDecision) -> dict[str, Any]:
        config = {"configurable": {"thread_id": run_id}}
        snapshot = await self.graph.aget_state(config)
        if not snapshot.values or not any(task.interrupts for task in snapshot.tasks):
            return {
                "status": "review_conflict",
                "error": "run is not awaiting review",
            }
        return await self.graph.ainvoke(
            Command(resume=decision.model_dump(mode="json")),
            config,
        )

    async def get(self, run_id: str) -> dict[str, Any]:
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": run_id}})
        values = dict(snapshot.values)
        if any(task.interrupts for task in snapshot.tasks):
            values["status"] = "awaiting_review"
        return values

    async def record_error(self, run_id: str, error: str) -> None:
        config = {"configurable": {"thread_id": run_id}}
        snapshot = await self.graph.aget_state(config)
        if snapshot.values:
            await self.graph.aupdate_state(
                config,
                {"status": "failed", "error": error},
            )

    async def advance_head(self, thesis_id: str) -> None:
        await self.connection.execute(
            "UPDATE thesis_heads SET version = version + 1 WHERE thesis_id = ?",
            (thesis_id,),
        )
        await self.connection.commit()

    async def close(self) -> None:
        await self.connection.close()
