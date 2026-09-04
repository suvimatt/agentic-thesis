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
    ArtifactFetchFailure,
    CollectionAttempt,
    DisclosureChunk,
    DisclosureDocument,
    DisclosureEvent,
    RadarEntry,
    RadarOutcome,
    ResearchState,
    ReviewDecision,
    RunStatus,
    SourceArtifact,
    ThesisDelta,
    ThesisSnapshot,
)
from agentic_thesis.rag import HybridRetriever, RetrievalHit, build_evidence_pack, enforce_citations


class AgenticThesisWorkflow:
    def __init__(
        self,
        database: str,
        connection: aiosqlite.Connection,
        checkpoint_connection: aiosqlite.Connection,
        checkpointer: AsyncSqliteSaver,
        retriever: Any,
        analyze: Callable[[ThesisSnapshot, list], Awaitable[ThesisDelta]],
    ) -> None:
        self.database = database
        self.connection = connection
        self.checkpoint_connection = checkpoint_connection
        self.checkpointer = checkpointer
        self.retriever = retriever
        self.analyze = analyze
        self.model_calls = asyncio.Semaphore(3)
        # ponytail: one local writer lock; split by thesis only if commit throughput matters.
        self.commit_lock = asyncio.Lock()
        self.ingest_lock = asyncio.Lock()
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
        version = int((await (await connection.execute("PRAGMA user_version")).fetchone())[0])
        tables = await (
            await connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ).fetchall()
        if tables and version != 11:
            await connection.close()
            raise RuntimeError(
                "AgenticThesis v1.1 requires an empty data directory; "
                "earlier SQLite databases are not supported"
            )
        if not tables:
            await connection.execute("PRAGMA user_version = 11")
            await connection.commit()
        await connection.execute("PRAGMA foreign_keys = ON")
        checkpoint_connection = await aiosqlite.connect(f"{database}.checkpoints")
        checkpointer = AsyncSqliteSaver(checkpoint_connection)
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
                disclosure_id TEXT NOT NULL,
                base_thesis_version INTEGER NOT NULL,
                status TEXT NOT NULL,
                validated_delta_json TEXT,
                evidence_packs_json TEXT,
                review_json TEXT,
                committed_thesis_version INTEGER,
                error TEXT,
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
                event_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_date TEXT NOT NULL,
                source_url TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                artifact_ids_json TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                canonical_text TEXT NOT NULL,
                chunks_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (thesis_id, event_id)
            );
            CREATE TABLE IF NOT EXISTS disclosure_events (
                event_id TEXT PRIMARY KEY,
                thesis_id TEXT NOT NULL,
                source TEXT NOT NULL,
                authority TEXT NOT NULL,
                event_type TEXT NOT NULL,
                external_id TEXT NOT NULL,
                event_date TEXT NOT NULL,
                published_at TEXT,
                accepted_at TEXT,
                amended_event_id TEXT,
                metadata_json TEXT NOT NULL,
                discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (thesis_id, source, external_id)
            );
            CREATE TABLE IF NOT EXISTS source_artifacts (
                artifact_id TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL UNIQUE,
                content BLOB NOT NULL,
                byte_length INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS event_artifacts (
                event_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                role TEXT NOT NULL,
                source_url TEXT NOT NULL,
                media_type TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                parser_name TEXT,
                parser_version TEXT,
                parse_status TEXT NOT NULL,
                parse_error TEXT,
                PRIMARY KEY (event_id, artifact_id, role),
                FOREIGN KEY (event_id) REFERENCES disclosure_events(event_id),
                FOREIGN KEY (artifact_id) REFERENCES source_artifacts(artifact_id)
            );
            CREATE TABLE IF NOT EXISTS artifact_fetch_failures (
                event_id TEXT NOT NULL,
                role TEXT NOT NULL,
                source_url TEXT NOT NULL,
                error TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                PRIMARY KEY (event_id, role, source_url),
                FOREIGN KEY (event_id) REFERENCES disclosure_events(event_id)
            );
            CREATE TABLE IF NOT EXISTS collection_attempts (
                attempt_id TEXT PRIMARY KEY,
                thesis_id TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                cursor_before TEXT,
                cursor_after TEXT,
                imported INTEGER NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS radar_entries (
                radar_id TEXT PRIMARY KEY,
                thesis_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL,
                matched_claim_ids_json TEXT NOT NULL,
                matched_falsifiers_json TEXT NOT NULL,
                run_id TEXT,
                policy_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (thesis_id, event_id, policy_version),
                FOREIGN KEY (event_id) REFERENCES disclosure_events(event_id)
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
            CREATE TABLE IF NOT EXISTS ir_monitors (
                thesis_id TEXT PRIMARY KEY,
                urls_json TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                last_checked_at TEXT,
                last_error TEXT,
                last_imported INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS ir_resources (
                thesis_id TEXT NOT NULL,
                root_url TEXT NOT NULL,
                resource_url TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                media_type TEXT NOT NULL,
                present INTEGER NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (thesis_id, root_url, resource_url)
            );
            """
        )
        await connection.commit()
        return cls(
            str(database),
            connection,
            checkpoint_connection,
            checkpointer,
            retriever,
            analyze,
        )

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
            *[
                self._retrieve_claim(
                    retriever,
                    claim.statement,
                    claim.falsifiers,
                )
                for claim in state.thesis.claims
            ]
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

    async def _retrieve_claim(
        self,
        retriever: Any,
        statement: str,
        falsifiers: list[str],
    ) -> tuple[list[RetrievalHit], dict[str, float | bool]]:
        queries = [statement]
        if falsifiers:
            queries.append("Evidence that would disprove the claim: " + " ".join(falsifiers))
        results = await asyncio.gather(
            *[self._search(retriever, query) for query in queries]
        )
        rankings = [
            [hit.chunk.chunk_id for hit in hits]
            for hits, _ in results
        ]
        fused = HybridRetriever.rrf(rankings, limit=6)
        chunks = {
            hit.chunk.chunk_id: hit.chunk
            for hits, _ in results
            for hit in hits
        }
        timings = {
            "retrieval_ms": round(
                sum(float(item.get("retrieval_ms", 0.0)) for _, item in results),
                3,
            ),
            "rerank_ms": round(
                sum(float(item.get("rerank_ms", 0.0)) for _, item in results),
                3,
            ),
            "rerank_triggered": any(
                bool(item.get("rerank_triggered", False)) for _, item in results
            ),
        }
        return (
            [RetrievalHit(chunks[chunk_id], score) for chunk_id, score in fused],
            timings,
        )

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
                    "\n".join([claim.statement, *claim.falsifiers]),
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
        await self._update_run(
            state.run_id,
            status=RunStatus.AWAITING_REVIEW,
            delta=state.delta,
            evidence_packs=state.evidence_packs,
        )
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
            await self._update_run(
                state.run_id,
                status=RunStatus.REJECTED,
                delta=state.delta,
                evidence_packs=state.evidence_packs,
                review=state.review,
            )
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
            await self._update_run(
                state.run_id,
                status=RunStatus.INVALID_REVIEW,
                delta=delta,
                evidence_packs=state.evidence_packs,
                review=state.review,
                error="review must contain exactly one delta per current claim",
            )
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
        async with self.commit_lock, aiosqlite.connect(self.database) as transaction:
            try:
                await transaction.execute("BEGIN IMMEDIATE")
                cursor = await transaction.execute(
                    "UPDATE thesis_heads SET version = ? WHERE thesis_id = ? AND version = ?",
                    (snapshot.version, snapshot.thesis_id, state.thesis.version),
                )
                if cursor.rowcount != 1:
                    await transaction.rollback()
                    await transaction.execute("BEGIN IMMEDIATE")
                    await self._update_run(
                        state.run_id,
                        status=RunStatus.VERSION_CONFLICT,
                        delta=delta,
                        evidence_packs=state.evidence_packs,
                        review=state.review,
                        error="base thesis version is stale",
                        connection=transaction,
                        commit=False,
                    )
                    await transaction.commit()
                    return {
                        "status": "version_conflict",
                        "error": "base thesis version is stale",
                        "timings_ms": self._timings(state, "commit_snapshot", started),
                    }
                await transaction.execute(
                    "INSERT INTO thesis_snapshots VALUES (?, ?, ?)",
                    (snapshot.thesis_id, snapshot.version, snapshot.model_dump_json()),
                )
                await self._update_run(
                    state.run_id,
                    status=RunStatus.COMMITTED,
                    delta=delta,
                    evidence_packs=state.evidence_packs,
                    review=state.review,
                    committed_thesis_version=snapshot.version,
                    connection=transaction,
                    commit=False,
                )
                await transaction.commit()
            except Exception:
                await transaction.rollback()
                raise
        return {
            "status": "committed",
            "thesis": snapshot,
            "timings_ms": self._timings(state, "commit_snapshot", started),
        }

    async def start(
        self,
        run_id: str,
        disclosure_id: str,
        thesis: ThesisSnapshot,
        chunks: list[DisclosureChunk],
    ) -> dict[str, Any]:
        state = self._initialize(run_id, disclosure_id, thesis, chunks)
        return await self.graph.ainvoke(state, {"configurable": {"thread_id": run_id}})

    async def stream_start(
        self,
        run_id: str,
        disclosure_id: str,
        thesis: ThesisSnapshot,
        chunks: list[DisclosureChunk],
    ) -> AsyncIterator[dict[str, Any]]:
        state = self._initialize(run_id, disclosure_id, thesis, chunks)
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

    @staticmethod
    def _initialize(
        run_id: str,
        disclosure_id: str,
        thesis: ThesisSnapshot,
        chunks: list[DisclosureChunk],
    ) -> ResearchState:
        return ResearchState(
            run_id=run_id,
            disclosure_id=disclosure_id,
            thesis=thesis,
            chunks=chunks,
        )

    async def _update_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        delta: ThesisDelta | None = None,
        evidence_packs: list | None = None,
        review: ReviewDecision | None = None,
        committed_thesis_version: int | None = None,
        error: str | None = None,
        connection: aiosqlite.Connection | None = None,
        commit: bool = True,
    ) -> None:
        target = connection or self.connection
        await target.execute(
            """
            UPDATE runs SET
                status = ?,
                validated_delta_json = COALESCE(?, validated_delta_json),
                evidence_packs_json = COALESCE(?, evidence_packs_json),
                review_json = COALESCE(?, review_json),
                committed_thesis_version = COALESCE(?, committed_thesis_version),
                error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE run_id = ?
            """,
            (
                status.value,
                delta.model_dump_json() if delta else None,
                json.dumps([pack.model_dump(mode="json") for pack in evidence_packs])
                if evidence_packs is not None
                else None,
                review.model_dump_json() if review else None,
                committed_thesis_version,
                error,
                run_id,
            ),
        )
        if commit:
            await target.commit()

    async def register_run(
        self, run_id: str, thesis: ThesisSnapshot, disclosure_id: str
    ) -> bool:
        cursor = await self.connection.execute(
            """
            INSERT OR IGNORE INTO runs
                (run_id, thesis_id, disclosure_id, base_thesis_version, status)
            VALUES (?, ?, ?, ?, 'running')
            """,
            (run_id, thesis.thesis_id, disclosure_id, thesis.version),
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
            SELECT run_id, thesis_id, disclosure_id, base_thesis_version, status,
                   validated_delta_json, evidence_packs_json, review_json,
                   committed_thesis_version, error
            FROM runs WHERE run_id = ?
            """,
            (run_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        keys = (
            "run_id", "thesis_id", "disclosure_id", "base_thesis_version",
            "status", "delta", "evidence_packs", "review",
            "committed_thesis_version", "error",
        )
        result = dict(zip(keys, row))
        for key in ("delta", "evidence_packs", "review"):
            result[key] = json.loads(result[key]) if result[key] else None
        result["evidence_packs"] = result["evidence_packs"] or []
        return result

    async def list_runs(self, thesis_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT run_id, thesis_id, disclosure_id, base_thesis_version, status,
                   committed_thesis_version, error
            FROM runs
        """
        params: tuple[str, ...] = ()
        if thesis_id is not None:
            query += " WHERE thesis_id = ?"
            params = (thesis_id,)
        query += " ORDER BY updated_at DESC, run_id"
        cursor = await self.connection.execute(query, params)
        keys = (
            "run_id", "thesis_id", "disclosure_id", "base_thesis_version",
            "status", "committed_thesis_version", "error",
        )
        return [dict(zip(keys, row)) for row in await cursor.fetchall()]

    async def create_thesis(self, thesis: ThesisSnapshot) -> bool:
        async with self.commit_lock, aiosqlite.connect(self.database) as transaction:
            try:
                await transaction.execute("BEGIN IMMEDIATE")
                cursor = await transaction.execute(
                    "INSERT OR IGNORE INTO thesis_heads VALUES (?, ?)",
                    (thesis.thesis_id, thesis.version),
                )
                if cursor.rowcount != 1:
                    await transaction.rollback()
                    return False
                await transaction.execute(
                    "INSERT INTO thesis_snapshots VALUES (?, ?, ?)",
                    (thesis.thesis_id, thesis.version, thesis.model_dump_json()),
                )
                await transaction.commit()
                return True
            except Exception:
                await transaction.rollback()
                raise

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

    async def get_thesis_version(
        self, thesis_id: str, version: int
    ) -> ThesisSnapshot | None:
        cursor = await self.connection.execute(
            "SELECT snapshot_json FROM thesis_snapshots WHERE thesis_id = ? AND version = ?",
            (thesis_id, version),
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
        document: DisclosureDocument | None,
        canonical_text: str,
        chunks: list[DisclosureChunk],
        event: DisclosureEvent,
        artifacts: list[tuple[SourceArtifact, bytes]],
        failures: list[ArtifactFetchFailure] | None = None,
        radar: RadarEntry | None = None,
        run: tuple[str, int] | None = None,
    ) -> tuple[bool, bool, RadarOutcome | None, str | None]:
        content_hash = (
            hashlib.sha256(
                "|".join(sorted(document.artifact_ids)).encode()
            ).hexdigest()
            if document else None
        )
        async with self.ingest_lock, aiosqlite.connect(self.database) as transaction:
            await transaction.execute("PRAGMA foreign_keys = ON")
            await transaction.execute("BEGIN IMMEDIATE")
            try:
                existing = await (
                    await transaction.execute(
                        """
                        SELECT thesis_id, source, external_id
                        FROM disclosure_events WHERE event_id = ?
                        """,
                        (event.event_id,),
                    )
                ).fetchone()
                identity = (event.thesis_id, event.source, event.external_id)
                if existing and existing != identity:
                    raise ValueError("event_id already identifies another event")
                identity_event = await (
                    await transaction.execute(
                        """
                        SELECT event_id FROM disclosure_events
                        WHERE thesis_id = ? AND source = ? AND external_id = ?
                        """,
                        identity,
                    )
                ).fetchone()
                if identity_event and identity_event[0] != event.event_id:
                    raise ValueError("source event already has another event_id")
                event_cursor = await transaction.execute(
                    """
                    INSERT OR IGNORE INTO disclosure_events
                        (event_id, thesis_id, source, authority, event_type,
                         external_id, event_date, published_at, accepted_at,
                         amended_event_id, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.thesis_id,
                        event.source,
                        event.authority,
                        event.event_type,
                        event.external_id,
                        event.event_date,
                        event.published_at,
                        event.accepted_at,
                        event.amended_event_id,
                        json.dumps(event.metadata, sort_keys=True),
                    ),
                )
                if event_cursor.rowcount != 1 and existing is None:
                    await transaction.rollback()
                    return False, False, None, None
                stored_radar = None
                if radar and event_cursor.rowcount == 0:
                    stored_radar = await (
                        await transaction.execute(
                            """
                            SELECT outcome, run_id FROM radar_entries
                            WHERE thesis_id = ? AND event_id = ? AND policy_version = ?
                            """,
                            (radar.thesis_id, radar.event_id, radar.policy_version),
                        )
                    ).fetchone()
                if stored_radar:
                    actual_outcome = RadarOutcome(stored_radar[0])
                    actual_run_id = stored_radar[1]
                    radar = None
                    run = None
                elif radar:
                    actual_outcome = radar.outcome
                    actual_run_id = radar.run_id
                else:
                    actual_outcome = None
                    actual_run_id = None
                exact_duplicate = False
                if document and event_cursor.rowcount == 1:
                    exact_duplicate = (
                        await (
                            await transaction.execute(
                                """
                                SELECT 1 FROM disclosures
                                WHERE thesis_id = ? AND content_hash = ? LIMIT 1
                                """,
                                (document.thesis_id, content_hash),
                            )
                        ).fetchone()
                        is not None
                    )
                if exact_duplicate and radar:
                    radar = radar.model_copy(
                        update={
                            "outcome": RadarOutcome.IGNORED,
                            "reason_codes": ["exact_duplicate"],
                            "matched_claim_ids": [],
                            "matched_falsifiers": [],
                            "run_id": None,
                        }
                    )
                    run = None
                    actual_outcome = radar.outcome
                    actual_run_id = None
                for artifact, content in artifacts:
                    await transaction.execute(
                        """
                        INSERT OR IGNORE INTO source_artifacts
                            (artifact_id, content_hash, content, byte_length)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            artifact.artifact_id,
                            artifact.content_hash,
                            content,
                            artifact.byte_length,
                        ),
                    )
                    await transaction.execute(
                        """
                        INSERT OR IGNORE INTO event_artifacts
                            (event_id, artifact_id, role, source_url, media_type, retrieved_at,
                             parser_name, parser_version, parse_status, parse_error)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.event_id,
                            artifact.artifact_id,
                            artifact.role,
                            artifact.source_url,
                            artifact.media_type,
                            artifact.retrieved_at,
                            artifact.parser_name,
                            artifact.parser_version,
                            artifact.parse_status,
                            artifact.parse_error,
                        ),
                    )
                for failure in failures or []:
                    await transaction.execute(
                        """
                        INSERT OR REPLACE INTO artifact_fetch_failures
                            (event_id, role, source_url, error, occurred_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            failure.event_id,
                            failure.role,
                            failure.source_url,
                            failure.error,
                            failure.occurred_at,
                        ),
                    )
                cursor = None
                if document:
                    cursor = await transaction.execute(
                        """
                        INSERT OR IGNORE INTO disclosures
                            (document_id, thesis_id, event_id, source_id, source_date,
                             source_url, content_hash, artifact_ids_json, raw_text,
                             canonical_text, chunks_json)
                        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        WHERE NOT EXISTS (
                            SELECT 1 FROM disclosures
                            WHERE thesis_id = ? AND source_id = ?
                        )
                        """,
                        (
                            document.document_id,
                            document.thesis_id,
                            event.event_id,
                            document.source_id,
                            document.source_date,
                            document.source_url,
                            content_hash,
                            json.dumps(document.artifact_ids),
                            document.content,
                            canonical_text,
                            json.dumps([chunk.model_dump(mode="json") for chunk in chunks]),
                            document.thesis_id,
                            document.source_id,
                        ),
                    )
                    if cursor.rowcount != 1 and event_cursor.rowcount == 1:
                        await transaction.rollback()
                        return False, False, None, None
                if radar:
                    await transaction.execute(
                        """
                        INSERT INTO radar_entries
                            (radar_id, thesis_id, event_id, outcome,
                             reason_codes_json, matched_claim_ids_json,
                             matched_falsifiers_json, run_id, policy_version,
                             created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            radar.radar_id,
                            radar.thesis_id,
                            radar.event_id,
                            radar.outcome,
                            json.dumps(radar.reason_codes),
                            json.dumps(radar.matched_claim_ids),
                            json.dumps(radar.matched_falsifiers),
                            radar.run_id,
                            radar.policy_version,
                            radar.created_at,
                        ),
                    )
                if run:
                    run_id, base_version = run
                    await transaction.execute(
                        """
                        INSERT INTO runs
                            (run_id, thesis_id, disclosure_id,
                             base_thesis_version, status)
                        VALUES (?, ?, ?, ?, 'running')
                        """,
                        (run_id, event.thesis_id, document.document_id, base_version),
                    )
                await transaction.commit()
                return (
                    event_cursor.rowcount == 1,
                    bool(cursor and cursor.rowcount == 1),
                    actual_outcome,
                    actual_run_id,
                )
            except Exception:
                await transaction.rollback()
                raise

    async def list_disclosures(self, thesis_id: str) -> list[dict[str, Any]]:
        cursor = await self.connection.execute(
            """
            SELECT document_id, thesis_id, source_id, source_date, source_url, event_id
            FROM disclosures WHERE thesis_id = ? ORDER BY source_date DESC, document_id
            """,
            (thesis_id,),
        )
        keys = (
            "document_id", "thesis_id", "source_id", "source_date", "source_url",
            "event_id",
        )
        return [dict(zip(keys, row)) for row in await cursor.fetchall()]

    async def get_disclosure(
        self, thesis_id: str, document_id: str
    ) -> DisclosureDocument | None:
        cursor = await self.connection.execute(
            """
            SELECT document_id, thesis_id, source_id, source_date, source_url,
                   raw_text, event_id, artifact_ids_json
            FROM disclosures WHERE thesis_id = ? AND document_id = ?
            """,
            (thesis_id, document_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return DisclosureDocument.model_validate(
            dict(
                zip(
                    (
                        "document_id", "thesis_id", "source_id", "source_date",
                        "source_url", "content", "event_id", "artifact_ids",
                    ),
                    (*row[:7], json.loads(row[7])),
                )
            )
        )

    async def chunks_for_disclosure(
        self, thesis_id: str, document_id: str
    ) -> list[DisclosureChunk]:
        cursor = await self.connection.execute(
            "SELECT chunks_json FROM disclosures WHERE thesis_id = ? AND document_id = ?",
            (thesis_id, document_id),
        )
        row = await cursor.fetchone()
        return [
            DisclosureChunk.model_validate(chunk)
            for chunk in json.loads(row[0])
        ] if row else []

    async def get_event(self, event_id: str) -> dict[str, Any] | None:
        cursor = await self.connection.execute(
            """
            SELECT event_id, thesis_id, source, authority, event_type, external_id,
                   event_date, published_at, accepted_at, amended_event_id,
                   metadata_json
            FROM disclosure_events WHERE event_id = ?
            """,
            (event_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        keys = (
            "event_id", "thesis_id", "source", "authority", "event_type",
            "external_id", "event_date", "published_at", "accepted_at",
            "amended_event_id", "metadata",
        )
        return dict(zip(keys, (*row[:10], json.loads(row[10]))))

    async def find_amended_event(
        self,
        thesis_id: str,
        source: str,
        base_form: str,
        report_date: str,
    ) -> str | None:
        rows = await (
            await self.connection.execute(
                """
                SELECT event_id, metadata_json
                FROM disclosure_events
                WHERE thesis_id = ? AND source = ?
                ORDER BY event_date DESC, discovered_at DESC
                """,
                (thesis_id, source),
            )
        ).fetchall()
        for event_id, metadata_json in rows:
            metadata = json.loads(metadata_json)
            if metadata.get("form") == base_form and (
                not report_date or metadata.get("report_date") == report_date
            ):
                return event_id
        return None

    async def list_artifacts(self, event_id: str) -> list[dict[str, Any]]:
        cursor = await self.connection.execute(
            """
            SELECT artifacts.artifact_id, links.event_id, links.role,
                   links.source_url, links.media_type, artifacts.content_hash,
                   artifacts.byte_length, links.retrieved_at, links.parser_name,
                   links.parser_version, links.parse_status, links.parse_error
            FROM event_artifacts AS links
            JOIN source_artifacts AS artifacts
              ON artifacts.artifact_id = links.artifact_id
            WHERE links.event_id = ?
            ORDER BY links.role, artifacts.artifact_id
            """,
            (event_id,),
        )
        keys = (
            "artifact_id", "event_id", "role", "source_url", "media_type",
            "content_hash", "byte_length", "retrieved_at", "parser_name",
            "parser_version", "parse_status", "parse_error",
        )
        return [dict(zip(keys, row)) for row in await cursor.fetchall()]

    async def get_artifact_content(self, artifact_id: str) -> bytes | None:
        row = await (
            await self.connection.execute(
                """
                SELECT content FROM source_artifacts WHERE artifact_id = ?
                """,
                (artifact_id,),
            )
        ).fetchone()
        return bytes(row[0]) if row else None

    async def record_artifact_failures(
        self, failures: list[ArtifactFetchFailure]
    ) -> None:
        if not failures:
            return
        await self.connection.executemany(
            """
            INSERT OR REPLACE INTO artifact_fetch_failures
                (event_id, role, source_url, error, occurred_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    failure.event_id,
                    failure.role,
                    failure.source_url,
                    failure.error,
                    failure.occurred_at,
                )
                for failure in failures
            ],
        )
        await self.connection.commit()

    async def list_artifact_failures(self, event_id: str) -> list[dict[str, str]]:
        cursor = await self.connection.execute(
            """
            SELECT event_id, role, source_url, error, occurred_at
            FROM artifact_fetch_failures WHERE event_id = ?
            ORDER BY role, source_url
            """,
            (event_id,),
        )
        keys = ("event_id", "role", "source_url", "error", "occurred_at")
        return [dict(zip(keys, row)) for row in await cursor.fetchall()]

    async def record_collection_attempt(self, attempt: CollectionAttempt) -> None:
        await self.connection.execute(
            """
            INSERT INTO collection_attempts
                (attempt_id, thesis_id, source, status, started_at, completed_at,
                 cursor_before, cursor_after, imported, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.attempt_id,
                attempt.thesis_id,
                attempt.source,
                attempt.status,
                attempt.started_at,
                attempt.completed_at,
                attempt.cursor_before,
                attempt.cursor_after,
                attempt.imported,
                attempt.error,
            ),
        )
        await self.connection.commit()

    async def list_collection_attempts(self, thesis_id: str) -> list[dict[str, Any]]:
        cursor = await self.connection.execute(
            """
            SELECT attempt_id, thesis_id, source, status, started_at, completed_at,
                   cursor_before, cursor_after, imported, error
            FROM collection_attempts
            WHERE thesis_id = ? ORDER BY started_at DESC, attempt_id DESC
            """,
            (thesis_id,),
        )
        keys = (
            "attempt_id", "thesis_id", "source", "status", "started_at",
            "completed_at", "cursor_before", "cursor_after", "imported", "error",
        )
        return [dict(zip(keys, row)) for row in await cursor.fetchall()]

    async def put_radar_entry(self, entry: RadarEntry) -> bool:
        cursor = await self.connection.execute(
            """
            INSERT OR IGNORE INTO radar_entries
                (radar_id, thesis_id, event_id, outcome, reason_codes_json,
                 matched_claim_ids_json, matched_falsifiers_json, run_id,
                 policy_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.radar_id,
                entry.thesis_id,
                entry.event_id,
                entry.outcome,
                json.dumps(entry.reason_codes),
                json.dumps(entry.matched_claim_ids),
                json.dumps(entry.matched_falsifiers),
                entry.run_id,
                entry.policy_version,
                entry.created_at,
            ),
        )
        await self.connection.commit()
        return cursor.rowcount == 1

    async def list_radar_entries(self, thesis_id: str) -> list[dict[str, Any]]:
        cursor = await self.connection.execute(
            """
            SELECT radar_id, thesis_id, event_id, outcome, reason_codes_json,
                   matched_claim_ids_json, matched_falsifiers_json, run_id,
                   policy_version, created_at
            FROM radar_entries WHERE thesis_id = ?
            ORDER BY created_at DESC, radar_id DESC
            """,
            (thesis_id,),
        )
        return [
            {
                "radar_id": row[0],
                "thesis_id": row[1],
                "event_id": row[2],
                "outcome": row[3],
                "reason_codes": json.loads(row[4]),
                "matched_claim_ids": json.loads(row[5]),
                "matched_falsifiers": json.loads(row[6]),
                "run_id": row[7],
                "policy_version": row[8],
                "created_at": row[9],
            }
            for row in await cursor.fetchall()
        ]

    async def list_revisions(self, thesis_id: str) -> list[dict[str, Any]]:
        cursor = await self.connection.execute(
            """
            SELECT run_id, thesis_id, disclosure_id, base_thesis_version,
                   committed_thesis_version, validated_delta_json,
                   evidence_packs_json, review_json
            FROM runs
            WHERE thesis_id = ? AND status = 'committed'
            ORDER BY committed_thesis_version
            """,
            (thesis_id,),
        )
        return [
            {
                "run_id": row[0],
                "thesis_id": row[1],
                "disclosure_id": row[2],
                "base_thesis_version": row[3],
                "committed_thesis_version": row[4],
                "delta": json.loads(row[5]),
                "evidence_packs": json.loads(row[6]),
                "review": json.loads(row[7]),
            }
            for row in await cursor.fetchall()
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

    async def configure_ir_monitor(
        self, thesis_id: str, urls: list[str], enabled: bool
    ) -> dict[str, Any]:
        await self.connection.execute(
            """
            INSERT INTO ir_monitors (thesis_id, urls_json, enabled)
            VALUES (?, ?, ?)
            ON CONFLICT(thesis_id) DO UPDATE SET
                urls_json = excluded.urls_json,
                enabled = excluded.enabled
            """,
            (thesis_id, json.dumps(urls), enabled),
        )
        await self.connection.commit()
        return await self.get_ir_monitor(thesis_id)

    async def get_ir_monitor(self, thesis_id: str) -> dict[str, Any] | None:
        row = await (
            await self.connection.execute(
                """
                SELECT thesis_id, urls_json, enabled, last_checked_at,
                       last_error, last_imported
                FROM ir_monitors WHERE thesis_id = ?
                """,
                (thesis_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return {
            "thesis_id": row[0],
            "urls": json.loads(row[1]),
            "enabled": bool(row[2]),
            "last_checked_at": row[3],
            "last_error": row[4],
            "last_imported": row[5],
        }

    async def list_ir_monitors(self) -> list[dict[str, Any]]:
        rows = await (
            await self.connection.execute(
                "SELECT thesis_id FROM ir_monitors ORDER BY thesis_id"
            )
        ).fetchall()
        return [await self.get_ir_monitor(row[0]) for row in rows]

    async def get_ir_resources(
        self, thesis_id: str, root_url: str
    ) -> dict[str, dict[str, Any]]:
        rows = await (
            await self.connection.execute(
                """
                SELECT resource_url, content_hash, media_type, present, last_seen_at
                FROM ir_resources WHERE thesis_id = ? AND root_url = ?
                """,
                (thesis_id, root_url),
            )
        ).fetchall()
        return {
            row[0]: {
                "content_hash": row[1],
                "media_type": row[2],
                "present": bool(row[3]),
                "last_seen_at": row[4],
            }
            for row in rows
        }

    async def record_ir_resources(
        self,
        thesis_id: str,
        root_url: str,
        resources: list[tuple[str, str, str]],
        observed_at: str,
    ) -> None:
        await self.connection.execute(
            """
            UPDATE ir_resources SET present = 0, last_seen_at = ?
            WHERE thesis_id = ? AND root_url = ?
            """,
            (observed_at, thesis_id, root_url),
        )
        for url, content_hash, media_type in resources:
            await self.connection.execute(
                """
                INSERT INTO ir_resources
                    (thesis_id, root_url, resource_url, content_hash,
                     media_type, present, last_seen_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(thesis_id, root_url, resource_url) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    media_type = excluded.media_type,
                    present = 1,
                    last_seen_at = excluded.last_seen_at
                """,
                (thesis_id, root_url, url, content_hash, media_type, observed_at),
            )
        await self.connection.commit()

    async def record_ir_sync(
        self, thesis_id: str, imported: int, error: str | None = None
    ) -> None:
        await self.connection.execute(
            """
            UPDATE ir_monitors
            SET last_checked_at = CASE
                    WHEN ? IS NULL THEN CURRENT_TIMESTAMP
                    ELSE last_checked_at
                END,
                last_error = ?,
                last_imported = ?
            WHERE thesis_id = ?
            """,
            (error, error, imported, thesis_id),
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
        await self._update_run(run_id, status=RunStatus.FAILED, error=error)

    async def advance_head(self, thesis_id: str) -> None:
        await self.connection.execute(
            "UPDATE thesis_heads SET version = version + 1 WHERE thesis_id = ?",
            (thesis_id,),
        )
        await self.connection.commit()

    async def close(self) -> None:
        await self.connection.close()
        await self.checkpoint_connection.close()
        if isinstance(self.retriever, HybridRetriever):
            self.retriever.close()
