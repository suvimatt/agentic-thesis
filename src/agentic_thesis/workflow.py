import asyncio
import hashlib
import json
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
    DisclosureDocument,
    ResearchState,
    ReviewDecision,
    ThesisDelta,
    ThesisSnapshot,
)
from agentic_thesis.rag import HybridRetriever, RetrievalHit, build_evidence_pack, enforce_citations


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
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                thesis_id TEXT NOT NULL,
                base_thesis_version INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS run_events (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (run_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS disclosures (
                document_id TEXT PRIMARY KEY,
                thesis_id TEXT NOT NULL,
                accession TEXT NOT NULL,
                filing_date TEXT NOT NULL,
                source_url TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                chunks_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (thesis_id, content_hash)
            );
            CREATE TABLE IF NOT EXISTS sec_monitors (
                thesis_id TEXT PRIMARY KEY,
                cik TEXT NOT NULL,
                forms_json TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                last_accession TEXT,
                last_checked_at TEXT,
                last_error TEXT,
                last_imported INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        await connection.commit()
        return cls(connection, checkpointer, retriever, analyze)

    async def _retrieve_claims(self, state: ResearchState) -> dict[str, Any]:
        started = perf_counter()
        retriever = self.retriever
        if isinstance(retriever, HybridRetriever) and [
            chunk.chunk_id for chunk in retriever.chunks
        ] != [chunk.chunk_id for chunk in state.chunks]:
            retriever = HybridRetriever(
                state.chunks,
                embed=retriever.embed,
                rerank=retriever.rerank,
                collection_name=retriever.collection_name,
                qdrant=retriever.qdrant,
            )
            await retriever.index()
        results = await asyncio.gather(
            *[self._search(retriever, claim.statement) for claim in state.thesis.claims]
        )
        return {
            "retrieved": {
                claim.claim_id: [hit.chunk.chunk_id for hit in result[0]]
                for claim, result in zip(state.thesis.claims, results, strict=True)
            },
            "retrieval_timings_ms": {
                claim.claim_id: result[1]
                for claim, result in zip(state.thesis.claims, results, strict=True)
            },
            "timings_ms": self._timings(state, "retrieve_claims", started),
        }

    @staticmethod
    def _timings(state: ResearchState, node: str, started: float) -> dict[str, float]:
        return {**state.timings_ms, node: round((perf_counter() - started) * 1_000, 3)}

    async def _search(
        self,
        retriever: Any,
        query: str,
    ) -> tuple[list[RetrievalHit], dict[str, float | bool]]:
        async with self.model_calls, asyncio.timeout(45):
            return await retriever.search_with_timings(query, limit=6)

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

    async def stream_resume(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        async for update in self.graph.astream(
            None,
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
        await self.connection.execute(
            """
            INSERT OR IGNORE INTO runs
                (run_id, thesis_id, base_thesis_version, status)
            VALUES (?, ?, ?, 'running')
            """,
            (run_id, thesis.thesis_id, thesis.version),
        )
        await self.connection.commit()
        return ResearchState(run_id=run_id, thesis=thesis, chunks=chunks)

    async def register_run(self, run_id: str, thesis: ThesisSnapshot) -> bool:
        cursor = await self.connection.execute(
            """
            INSERT OR IGNORE INTO runs
                (run_id, thesis_id, base_thesis_version, status)
            VALUES (?, ?, ?, 'running')
            """,
            (run_id, thesis.thesis_id, thesis.version),
        )
        await self.connection.commit()
        return cursor.rowcount == 1

    async def append_event(self, run_id: str, event: dict[str, Any]) -> int:
        cursor = await self.connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM run_events WHERE run_id = ?",
            (run_id,),
        )
        sequence = int((await cursor.fetchone())[0])
        await self.connection.execute(
            "INSERT INTO run_events (run_id, sequence, event_json) VALUES (?, ?, ?)",
            (run_id, sequence, json.dumps(event)),
        )
        await self.connection.execute(
            "UPDATE runs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (event.get("status", "running"), run_id),
        )
        await self.connection.commit()
        return sequence

    async def list_events(self, run_id: str, after: int = 0) -> list[tuple[int, dict]]:
        cursor = await self.connection.execute(
            """
            SELECT sequence, event_json
            FROM run_events
            WHERE run_id = ? AND sequence > ?
            ORDER BY sequence
            """,
            (run_id, after),
        )
        return [(row[0], json.loads(row[1])) for row in await cursor.fetchall()]

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        cursor = await self.connection.execute(
            """
            SELECT run_id, thesis_id, base_thesis_version, status
            FROM runs WHERE run_id = ?
            """,
            (run_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(zip(("run_id", "thesis_id", "base_thesis_version", "status"), row))

    async def list_runs(self, thesis_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT run_id, thesis_id, base_thesis_version, status
            FROM runs
        """
        params: tuple[str, ...] = ()
        if thesis_id is not None:
            query += " WHERE thesis_id = ?"
            params = (thesis_id,)
        query += " ORDER BY updated_at DESC, run_id"
        cursor = await self.connection.execute(query, params)
        keys = ("run_id", "thesis_id", "base_thesis_version", "status")
        return [dict(zip(keys, row)) for row in await cursor.fetchall()]

    async def create_thesis(self, thesis: ThesisSnapshot) -> bool:
        cursor = await self.connection.execute(
            "INSERT OR IGNORE INTO thesis_heads VALUES (?, ?)",
            (thesis.thesis_id, thesis.version),
        )
        if cursor.rowcount != 1:
            await self.connection.rollback()
            return False
        await self.connection.execute(
            "INSERT INTO thesis_snapshots VALUES (?, ?, ?)",
            (thesis.thesis_id, thesis.version, thesis.model_dump_json()),
        )
        await self.connection.commit()
        return True

    async def get_thesis(self, thesis_id: str) -> ThesisSnapshot | None:
        cursor = await self.connection.execute(
            """
            SELECT snapshots.snapshot_json
            FROM thesis_heads AS heads
            JOIN thesis_snapshots AS snapshots
              ON snapshots.thesis_id = heads.thesis_id
             AND snapshots.version = heads.version
            WHERE heads.thesis_id = ?
            """,
            (thesis_id,),
        )
        row = await cursor.fetchone()
        return ThesisSnapshot.model_validate_json(row[0]) if row else None

    async def list_theses(self) -> list[ThesisSnapshot]:
        cursor = await self.connection.execute(
            """
            SELECT snapshots.snapshot_json
            FROM thesis_heads AS heads
            JOIN thesis_snapshots AS snapshots
              ON snapshots.thesis_id = heads.thesis_id
             AND snapshots.version = heads.version
            ORDER BY snapshots.thesis_id
            """
        )
        return [ThesisSnapshot.model_validate_json(row[0]) for row in await cursor.fetchall()]

    async def add_disclosure(
        self,
        document: DisclosureDocument,
        chunks: list[DisclosureChunk],
    ) -> bool:
        content_hash = hashlib.sha256(document.content.encode()).hexdigest()
        cursor = await self.connection.execute(
            """
            INSERT OR IGNORE INTO disclosures
                (document_id, thesis_id, accession, filing_date, source_url,
                 content_hash, raw_text, chunks_json)
            SELECT ?, ?, ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM disclosures
                WHERE thesis_id = ? AND accession = ?
            )
            """,
            (
                document.document_id,
                document.thesis_id,
                document.accession,
                document.filing_date,
                document.source_url,
                content_hash,
                document.content,
                json.dumps([chunk.model_dump(mode="json") for chunk in chunks]),
                document.thesis_id,
                document.accession,
            ),
        )
        await self.connection.commit()
        return cursor.rowcount == 1

    async def list_disclosures(self, thesis_id: str) -> list[dict[str, Any]]:
        cursor = await self.connection.execute(
            """
            SELECT document_id, thesis_id, accession, filing_date, source_url
            FROM disclosures WHERE thesis_id = ? ORDER BY filing_date DESC, document_id
            """,
            (thesis_id,),
        )
        keys = ("document_id", "thesis_id", "accession", "filing_date", "source_url")
        return [dict(zip(keys, row)) for row in await cursor.fetchall()]

    async def chunks_for_thesis(self, thesis_id: str) -> list[DisclosureChunk]:
        cursor = await self.connection.execute(
            "SELECT chunks_json FROM disclosures WHERE thesis_id = ? ORDER BY filing_date, document_id",
            (thesis_id,),
        )
        return [
            DisclosureChunk.model_validate(chunk)
            for row in await cursor.fetchall()
            for chunk in json.loads(row[0])
        ]

    async def configure_sec_monitor(
        self,
        thesis_id: str,
        cik: str,
        forms: list[str],
        enabled: bool,
    ) -> dict[str, Any]:
        await self.connection.execute(
            """
            INSERT INTO sec_monitors (thesis_id, cik, forms_json, enabled)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thesis_id) DO UPDATE SET
                cik = excluded.cik,
                forms_json = excluded.forms_json,
                enabled = excluded.enabled,
                last_accession = CASE
                    WHEN cik = excluded.cik AND forms_json = excluded.forms_json
                    THEN last_accession
                    ELSE NULL
                END
            """,
            (thesis_id, cik, json.dumps(forms), enabled),
        )
        await self.connection.commit()
        return await self.get_sec_monitor(thesis_id)

    async def get_sec_monitor(self, thesis_id: str) -> dict[str, Any] | None:
        cursor = await self.connection.execute(
            """
            SELECT thesis_id, cik, forms_json, enabled, last_accession,
                   last_checked_at, last_error, last_imported
            FROM sec_monitors WHERE thesis_id = ?
            """,
            (thesis_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "thesis_id": row[0],
            "cik": row[1],
            "forms": json.loads(row[2]),
            "enabled": bool(row[3]),
            "last_accession": row[4],
            "last_checked_at": row[5],
            "last_error": row[6],
            "last_imported": row[7],
        }

    async def list_sec_monitors(self) -> list[dict[str, Any]]:
        cursor = await self.connection.execute(
            "SELECT thesis_id FROM sec_monitors ORDER BY thesis_id"
        )
        return [
            await self.get_sec_monitor(row[0])
            for row in await cursor.fetchall()
        ]

    async def record_sec_sync(
        self,
        thesis_id: str,
        *,
        last_accession: str | None,
        imported: int,
        error: str | None = None,
    ) -> None:
        await self.connection.execute(
            """
            UPDATE sec_monitors
            SET last_accession = COALESCE(?, last_accession),
                last_checked_at = CASE
                    WHEN ? IS NULL THEN CURRENT_TIMESTAMP
                    ELSE last_checked_at
                END,
                last_error = ?,
                last_imported = ?
            WHERE thesis_id = ?
            """,
            (last_accession, error, error, imported, thesis_id),
        )
        await self.connection.commit()

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
        if isinstance(self.retriever, HybridRetriever):
            self.retriever.close()
