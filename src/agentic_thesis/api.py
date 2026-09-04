import asyncio
import hashlib
import json
import os
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

from agentic_thesis.engine import AgenticThesisEngine, EngineConflictError
from agentic_thesis.models import (
    DisclosureDocument,
    DisclosureSummary,
    ReviewDecision,
    RunStatus,
    RunSummary,
    SecMonitor,
    ThesisRevision,
    ThesisRun,
    ThesisSnapshot,
)
from agentic_thesis.rag import OpenAIModel
from agentic_thesis.workflow import AgenticThesisWorkflow


class StartRun(BaseModel):
    run_id: str
    thesis_id: str
    disclosure_id: str


class SecMonitorInput(BaseModel):
    cik: str = Field(pattern=r"^\d{1,10}$")
    forms: list[str] = Field(min_length=1, max_length=20)
    enabled: bool = True

    @field_validator("cik")
    @classmethod
    def normalize_cik(cls, value: str) -> str:
        return value.zfill(10)

    @field_validator("forms")
    @classmethod
    def normalize_forms(cls, values: list[str]) -> list[str]:
        forms = list(dict.fromkeys(value.strip().upper() for value in values))
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-/")
        if any(
            not form or len(form) > 20 or not set(form) <= allowed
            for form in forms
        ):
            raise ValueError("filing forms contain invalid characters")
        return forms


class SecEdgarClient:
    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent

    def _read(self, url: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "application/json,text/html"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read(10_000_001)
        if len(content) > 10_000_000:
            raise ValueError("SEC response exceeds 10 MB")
        return content

    async def recent_filings(self, cik: str) -> list[dict[str, str]]:
        payload = json.loads(
            await asyncio.to_thread(
                self._read,
                f"https://data.sec.gov/submissions/CIK{cik}.json",
            )
        )
        recent = payload["filings"]["recent"]
        return [
            {
                "accession": accession,
                "filing_date": recent["filingDate"][index],
                "form": recent["form"][index],
                "primary_document": recent["primaryDocument"][index],
            }
            for index, accession in enumerate(recent["accessionNumber"])
        ]

    async def filing_html(
        self,
        cik: str,
        filing: dict[str, str],
    ) -> tuple[str, str]:
        accession = filing["accession"].replace("-", "")
        document = urllib.parse.quote(filing["primary_document"], safe="")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{document}"
        content = await asyncio.to_thread(self._read, url)
        return content.decode("utf-8", errors="ignore"), url


def _public_state(state: ThesisRun) -> dict:
    payload = state.model_dump(mode="json")
    payload["total_ms"] = round(sum(state.timings_ms.values()), 3)
    return jsonable_encoder(payload)


async def _default_engine() -> AgenticThesisEngine:
    data_dir = Path(
        os.getenv("AGENTIC_THESIS_DATA_DIR", Path.home() / ".agentic-thesis")
    ).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(data_dir / ".env")
    sample_data = files("agentic_thesis").joinpath("sample_data")
    thesis = ThesisSnapshot.model_validate_json(
        sample_data.joinpath("thesis_v1.json").read_text()
    )
    filings = [
        (
            "aapl-2023",
            "2023-09-30",
            "aapl-2023-10-k.html",
            "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm",
        ),
        (
            "aapl-2024",
            "2024-09-28",
            "aapl-2024-10-k.html",
            "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
        ),
    ]
    documents = {
        accession: sample_data.joinpath("filings", filename).read_text(errors="ignore")
        for accession, _, filename, _ in filings
    }
    model = OpenAIModel(
        AsyncOpenAI(),
        embedding_client=AsyncOpenAI(
            api_key=os.environ["EMBEDDING_API_KEY"],
            base_url=os.environ["EMBEDDING_BASE_URL"],
        ),
        model=os.getenv("AGENTIC_THESIS_MODEL", "gpt-5-mini"),
        embedding_model=os.environ["AGENTIC_THESIS_EMBEDDING_MODEL"],
    )
    collection_name = "chunks_" + hashlib.sha256(
        (
            os.environ["EMBEDDING_BASE_URL"]
            + "|"
            + os.environ["AGENTIC_THESIS_EMBEDDING_MODEL"]
        ).encode()
    ).hexdigest()[:16]
    engine = await AgenticThesisEngine.open_local(
        data_dir,
        embed=model.embed,
        rerank=model.rerank,
        analyze=model.analyze,
        collection_name=collection_name,
    )
    if await engine.get_thesis(thesis.thesis_id) is None:
        await engine.create_thesis(thesis)
    for accession, filing_date, _, source_url in filings:
        if await engine.get_disclosure(thesis.thesis_id, accession) is None:
            await engine.add_disclosure(
                DisclosureDocument(
                    document_id=accession,
                    thesis_id=thesis.thesis_id,
                    accession=accession,
                    filing_date=filing_date,
                    source_url=source_url,
                    content=documents[accession],
                )
            )
    return engine


def create_app(
    engine: AgenticThesisEngine | AgenticThesisWorkflow | None = None,
    *,
    sec_client: Any = None,
    monitor_interval: float | None = None,
    collection_interval: float = 86_400,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if engine is None:
            app.state.engine = await _default_engine()
            user_agent = os.getenv("AGENTIC_THESIS_SEC_USER_AGENT")
            if app.state.sec_client is None and user_agent:
                app.state.sec_client = SecEdgarClient(user_agent)
            if app.state.monitor_interval is None:
                app.state.monitor_interval = float(
                    os.getenv("AGENTIC_THESIS_SEC_POLL_SECONDS", "3600")
                )
        for run in await app.state.engine.list_runs():
            if run.status == RunStatus.RUNNING:
                app.state.run_conditions[run.run_id] = asyncio.Condition()
                app.state.run_tasks[run.run_id] = asyncio.create_task(
                    execute_run(run.run_id)
                )
        if app.state.monitor_interval is not None:
            app.state.monitor_task = asyncio.create_task(poll_sec_monitors())
        yield
        if app.state.monitor_task is not None:
            app.state.monitor_task.cancel()
            await asyncio.gather(app.state.monitor_task, return_exceptions=True)
        pending = [task for task in app.state.run_tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if engine is None:
            await app.state.engine.close()

    app = FastAPI(title="AgenticThesis", version="0.9.0", lifespan=lifespan)
    if engine is not None:
        app.state.engine = (
            engine
            if isinstance(engine, AgenticThesisEngine)
            else AgenticThesisEngine(engine)
        )
    app.state.run_tasks = {}
    app.state.run_conditions = {}
    app.state.sec_client = sec_client
    app.state.monitor_interval = monitor_interval
    app.state.collection_interval = collection_interval
    app.state.monitor_task = None

    async def publish(run_id: str, event: dict) -> None:
        event = jsonable_encoder(event)
        condition = app.state.run_conditions.setdefault(run_id, asyncio.Condition())
        async with condition:
            await app.state.engine.append_event(run_id, event)
            condition.notify_all()

    async def execute_run(
        run_id: str,
    ) -> None:
        terminal = False
        try:
            async for update in app.state.engine.execute_run(run_id):
                for node, payload in update.items():
                    if node == "__interrupt__":
                        await publish(
                            run_id,
                            {"node": "human_review", "status": "awaiting_review", "error": None},
                        )
                        terminal = True
                        continue
                    event = {
                        "node": node,
                        "status": "running",
                        "latency_ms": payload.get("timings_ms", {}).get(node),
                        "total_ms": round(sum(payload.get("timings_ms", {}).values()), 3),
                        "error": None,
                    }
                    if node == "retrieve_claims":
                        event["claims"] = [
                            {"claim_id": claim_id, **timings}
                            for claim_id, timings in payload.get(
                                "retrieval_timings_ms",
                                {},
                            ).items()
                        ]
                    if node == "build_evidence_packs":
                        event["claims"] = [
                            {
                                "claim_id": pack.claim_id,
                                "tokens_before": pack.tokens_before,
                                "tokens_after": pack.tokens_after,
                            }
                            for pack in payload.get("evidence_packs", [])
                        ]
                    await publish(run_id, event)
            if not terminal:
                state = await app.state.engine.get_run(run_id)
                await publish(
                    run_id,
                    {
                        "node": "workflow",
                        "status": state.status,
                        "error": state.error,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = str(exc)
            await publish(
                run_id,
                {"node": "workflow", "status": "failed", "error": error},
            )

    async def launch_run(
        run_id: str,
        thesis_id: str,
        disclosure_id: str,
    ) -> None:
        existing = app.state.run_tasks.get(run_id)
        if existing and not existing.done():
            raise HTTPException(status_code=409, detail="run is already active")
        app.state.run_conditions[run_id] = asyncio.Condition()
        try:
            await app.state.engine.start_run(run_id, thesis_id, disclosure_id)
        except EngineConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        app.state.run_tasks[run_id] = asyncio.create_task(
            execute_run(run_id)
        )

    @app.get("/", response_class=FileResponse)
    async def product_page() -> FileResponse:
        return FileResponse(Path(__file__).with_name("index.html"))

    @app.post("/runs", status_code=202)
    async def start_run(request: StartRun) -> dict:
        await launch_run(request.run_id, request.thesis_id, request.disclosure_id)
        return {"run_id": request.run_id, "status": "running"}

    @app.get("/theses")
    async def list_theses() -> list[ThesisSnapshot]:
        return await app.state.engine.list_theses()

    @app.post("/theses", status_code=201)
    async def create_thesis(thesis: ThesisSnapshot) -> ThesisSnapshot:
        try:
            return await app.state.engine.create_thesis(thesis)
        except EngineConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/theses/{thesis_id}")
    async def get_thesis(thesis_id: str) -> ThesisSnapshot:
        thesis = await app.state.engine.get_thesis(thesis_id)
        if thesis is None:
            raise HTTPException(status_code=404, detail="thesis not found")
        return thesis

    @app.get("/monitors")
    async def list_monitors() -> list[SecMonitor]:
        return await app.state.engine.list_sec_monitors()

    @app.put("/theses/{thesis_id}/monitor")
    async def configure_monitor(
        thesis_id: str, request: SecMonitorInput
    ) -> SecMonitor:
        try:
            return await app.state.engine.configure_sec_monitor(
                thesis_id, request.cik, request.forms, request.enabled
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def sync_sec_monitor(thesis_id: str) -> dict:
        monitor = await app.state.engine.get_sec_monitor(thesis_id)
        if monitor is None:
            raise HTTPException(status_code=404, detail="SEC monitor not configured")
        if not monitor.enabled:
            raise HTTPException(status_code=409, detail="SEC monitor is paused")
        if app.state.sec_client is None:
            raise HTTPException(
                status_code=503,
                detail="Set AGENTIC_THESIS_SEC_USER_AGENT to a name and contact email",
            )
        try:
            filings = await app.state.sec_client.recent_filings(monitor.cik)
            matching = [item for item in filings if item["form"] in monitor.forms]
            if monitor.last_accession:
                accessions = [item["accession"] for item in matching]
                candidates = (
                    matching[: accessions.index(monitor.last_accession)]
                    if monitor.last_accession in accessions
                    else matching[:1]
                )
            else:
                candidates = matching[:1]
            run_ids = []
            for filing in reversed(candidates):
                content, source_url = await app.state.sec_client.filing_html(
                    monitor.cik, filing
                )
                document = DisclosureDocument(
                    document_id=f"{thesis_id}:{filing['accession']}",
                    thesis_id=thesis_id,
                    accession=filing["accession"],
                    filing_date=filing["filing_date"],
                    source_url=source_url,
                    content=content,
                )
                try:
                    await app.state.engine.add_disclosure(document)
                except EngineConflictError:
                    continue
                run_id = f"sec-{thesis_id}-{filing['accession']}"
                await launch_run(run_id, thesis_id, document.document_id)
                run_ids.append(run_id)
            await app.state.engine.record_sec_sync(
                thesis_id,
                last_accession=matching[0]["accession"] if matching else None,
                imported=len(run_ids),
            )
        except HTTPException:
            raise
        except Exception as exc:
            await app.state.engine.record_sec_sync(
                thesis_id,
                last_accession=None,
                imported=0,
                error=str(exc),
            )
            raise HTTPException(status_code=502, detail=f"SEC sync failed: {exc}") from exc
        return {
            "thesis_id": thesis_id,
            "checked": len(matching),
            "imported": len(run_ids),
            "run_ids": run_ids,
        }

    async def poll_sec_monitors() -> None:
        while True:
            for monitor in await app.state.engine.list_sec_monitors():
                if not monitor.enabled:
                    continue
                if monitor.last_checked_at:
                    checked_at = datetime.fromisoformat(
                        monitor.last_checked_at
                    ).replace(tzinfo=timezone.utc)
                    if (
                        datetime.now(timezone.utc) - checked_at
                    ).total_seconds() < app.state.collection_interval:
                        continue
                try:
                    await sync_sec_monitor(monitor.thesis_id)
                except HTTPException:
                    pass
            await asyncio.sleep(app.state.monitor_interval)

    @app.post("/theses/{thesis_id}/sync")
    async def sync_monitor(thesis_id: str) -> dict:
        return await sync_sec_monitor(thesis_id)

    @app.get("/disclosures")
    async def list_disclosures(thesis_id: str) -> list[DisclosureSummary]:
        return await app.state.engine.list_disclosures(thesis_id)

    @app.post("/disclosures", status_code=201)
    async def create_disclosure(document: DisclosureDocument) -> dict:
        try:
            chunk_count = await app.state.engine.add_disclosure(document)
        except EngineConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            status = 404 if str(exc) == "thesis not found" else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        return {
            "document_id": document.document_id,
            "thesis_id": document.thesis_id,
            "chunk_count": chunk_count,
        }

    @app.get("/runs")
    async def list_runs(thesis_id: str | None = None) -> list[RunSummary]:
        return await app.state.engine.list_runs(thesis_id)

    @app.get("/theses/{thesis_id}/revisions")
    async def list_revisions(thesis_id: str) -> list[ThesisRevision]:
        return await app.state.engine.list_revisions(thesis_id)

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict:
        state = await app.state.engine.get_run(run_id)
        if not state:
            raise HTTPException(status_code=404, detail="run not found")
        return _public_state(state)

    @app.get("/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request) -> StreamingResponse:
        if await app.state.engine.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")

        try:
            after = int(request.headers.get("last-event-id", "0"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc

        async def stream() -> AsyncIterator[str]:
            sequence = after
            condition = app.state.run_conditions.setdefault(run_id, asyncio.Condition())
            while True:
                async with condition:
                    events = await app.state.engine.list_events(run_id, sequence)
                    if not events:
                        run = await app.state.engine.get_run(run_id)
                        if run.status in {
                            "committed",
                            "rejected",
                            "failed",
                            "version_conflict",
                            "invalid_review",
                        }:
                            return
                        await condition.wait()
                        continue
                for sequence, event in events:
                    yield f"id: {sequence}\nevent: state\ndata: {json.dumps(event)}\n\n"
                    if event["status"] in {
                        "awaiting_review",
                        "committed",
                        "rejected",
                        "failed",
                        "version_conflict",
                        "invalid_review",
                    }:
                        return

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/runs/{run_id}/review")
    async def review_run(run_id: str, decision: ReviewDecision) -> dict:
        try:
            result = await app.state.engine.review(run_id, decision)
        except EngineConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if result.status == RunStatus.VERSION_CONFLICT:
            await publish(
                run_id,
                {
                    "node": "human_review",
                    "status": "version_conflict",
                    "error": result.error,
                },
            )
            raise HTTPException(status_code=409, detail=result.error)
        if result.status == RunStatus.INVALID_REVIEW:
            await publish(
                run_id,
                {
                    "node": "human_review",
                    "status": "invalid_review",
                    "error": result.error,
                },
            )
            raise HTTPException(status_code=422, detail=result.error)
        await publish(
            run_id,
            {
                "node": "human_review",
                "status": result.status,
                "error": result.error,
            },
        )
        return _public_state(result)

    return app


app = create_app()
