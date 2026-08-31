import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel

from agentic_thesis.models import DisclosureChunk, ReviewDecision, ThesisSnapshot
from agentic_thesis.rag import HybridRetriever, OpenAIModel, chunk_filing
from agentic_thesis.workflow import AgenticThesisWorkflow


class StartRun(BaseModel):
    run_id: str
    thesis: ThesisSnapshot | None = None
    chunks: list[DisclosureChunk] | None = None


def _public_state(run_id: str, state: dict) -> dict:
    return jsonable_encoder(
        {
            "run_id": run_id,
            "status": state.get("status", "running"),
            "thesis": state.get("thesis"),
            "delta": state.get("delta"),
            "evidence_packs": state.get("evidence_packs", []),
            "timings_ms": state.get("timings_ms", {}),
            "error": state.get("error"),
        }
    )


async def _default_workflow() -> tuple[AgenticThesisWorkflow, ThesisSnapshot, list[DisclosureChunk]]:
    root = Path(__file__).parents[2]
    load_dotenv(root / ".env", override=True)
    thesis = ThesisSnapshot.model_validate_json((root / "data/thesis_v1.json").read_text())
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
    chunks = [
        chunk
        for accession, filing_date, filename, source_url in filings
        for chunk in chunk_filing(
            (root / "data/filings" / filename).read_text(errors="ignore"),
            accession=accession,
            filing_date=filing_date,
            source_url=source_url,
        )
    ]
    model = OpenAIModel(
        AsyncOpenAI(),
        embedding_client=AsyncOpenAI(
            api_key=os.environ["EMBEDDING_API_KEY"],
            base_url=os.environ["EMBEDDING_BASE_URL"],
        ),
        model=os.getenv("AGENTIC_THESIS_MODEL", "gpt-5-mini"),
        embedding_model=os.environ["AGENTIC_THESIS_EMBEDDING_MODEL"],
    )
    retriever = HybridRetriever(chunks, embed=model.embed, rerank=model.rerank)
    await retriever.index()
    workflow = await AgenticThesisWorkflow.create(
        root / "data/agentic_thesis.sqlite",
        retriever,
        model.analyze,
    )
    return workflow, thesis, chunks


def create_app(workflow: AgenticThesisWorkflow | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if workflow is None:
            app.state.workflow, app.state.thesis, app.state.chunks = await _default_workflow()
        yield
        for task in app.state.run_tasks.values():
            if not task.done():
                task.cancel()
        if workflow is None:
            await app.state.workflow.close()

    app = FastAPI(title="AgenticThesis", version="0.1.0", lifespan=lifespan)
    if workflow is not None:
        app.state.workflow = workflow
        app.state.thesis = None
        app.state.chunks = None
    app.state.run_tasks = {}
    app.state.run_events = {}
    app.state.run_conditions = {}

    async def publish(run_id: str, event: dict) -> None:
        condition = app.state.run_conditions[run_id]
        async with condition:
            app.state.run_events[run_id].append(jsonable_encoder(event))
            condition.notify_all()

    async def execute_run(
        run_id: str,
        thesis: ThesisSnapshot,
        chunks: list[DisclosureChunk],
    ) -> None:
        terminal = False
        try:
            async for update in app.state.workflow.stream_start(run_id, thesis, chunks):
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
                        "error": None,
                    }
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
                state = await app.state.workflow.get(run_id)
                await publish(
                    run_id,
                    {
                        "node": "workflow",
                        "status": state.get("status", "completed"),
                        "error": state.get("error"),
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = str(exc)
            await app.state.workflow.record_error(run_id, error)
            await publish(
                run_id,
                {"node": "workflow", "status": "failed", "error": error},
            )

    @app.get("/", response_class=FileResponse)
    async def product_page() -> FileResponse:
        return FileResponse(Path(__file__).with_name("index.html"))

    @app.post("/runs", status_code=202)
    async def start_run(request: StartRun) -> dict:
        thesis = request.thesis
        if thesis is None and app.state.thesis is not None:
            thesis = await app.state.workflow.current_snapshot(app.state.thesis)
        chunks = request.chunks or app.state.chunks
        if thesis is None or chunks is None:
            raise HTTPException(status_code=422, detail="thesis and chunks are required")
        existing = app.state.run_tasks.get(request.run_id)
        if existing and not existing.done():
            raise HTTPException(status_code=409, detail="run is already active")
        app.state.run_events[request.run_id] = []
        app.state.run_conditions[request.run_id] = asyncio.Condition()
        app.state.run_tasks[request.run_id] = asyncio.create_task(
            execute_run(request.run_id, thesis, chunks)
        )
        return {"run_id": request.run_id, "status": "running"}

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict:
        state = await app.state.workflow.get(run_id)
        if not state:
            raise HTTPException(status_code=404, detail="run not found")
        return _public_state(run_id, state)

    @app.get("/runs/{run_id}/events")
    async def run_events(run_id: str) -> StreamingResponse:
        if run_id not in app.state.run_events:
            raise HTTPException(status_code=404, detail="run not found")

        async def stream() -> AsyncIterator[str]:
            index = 0
            condition = app.state.run_conditions[run_id]
            while True:
                async with condition:
                    await condition.wait_for(
                        lambda: index < len(app.state.run_events[run_id])
                    )
                    events = app.state.run_events[run_id][index:]
                    index += len(events)
                for event in events:
                    yield f"event: state\ndata: {json.dumps(event)}\n\n"
                    if event["status"] in {"awaiting_review", "committed", "rejected", "failed"}:
                        return

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/runs/{run_id}/review")
    async def review_run(run_id: str, decision: ReviewDecision) -> dict:
        result = await app.state.workflow.resume(run_id, decision)
        if result.get("status") == "version_conflict":
            raise HTTPException(status_code=409, detail=result["error"])
        if result.get("status") == "review_conflict":
            raise HTTPException(status_code=409, detail=result["error"])
        if result.get("status") == "invalid_review":
            raise HTTPException(status_code=422, detail=result["error"])
        return _public_state(run_id, result)

    return app


app = create_app()
