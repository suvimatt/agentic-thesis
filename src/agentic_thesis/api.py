import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
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
        model=os.getenv("AGENTIC_THESIS_MODEL", "gpt-5-mini"),
        embedding_model=os.getenv("AGENTIC_THESIS_EMBEDDING_MODEL", "text-embedding-3-small"),
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
        if workflow is None:
            await app.state.workflow.close()

    app = FastAPI(title="AgenticThesis", version="0.1.0", lifespan=lifespan)
    if workflow is not None:
        app.state.workflow = workflow
        app.state.thesis = None
        app.state.chunks = None

    @app.post("/runs")
    async def start_run(request: StartRun) -> dict:
        thesis = request.thesis or app.state.thesis
        chunks = request.chunks or app.state.chunks
        if thesis is None or chunks is None:
            raise HTTPException(status_code=422, detail="thesis and chunks are required")
        result = await app.state.workflow.start(request.run_id, thesis, chunks)
        status = "awaiting_review" if result.get("__interrupt__") else result.get("status", "running")
        return {"run_id": request.run_id, "status": status}

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict:
        state = await app.state.workflow.get(run_id)
        if not state:
            raise HTTPException(status_code=404, detail="run not found")
        return _public_state(run_id, state)

    @app.get("/runs/{run_id}/events")
    async def run_events(run_id: str) -> StreamingResponse:
        state = await app.state.workflow.get(run_id)
        if not state:
            raise HTTPException(status_code=404, detail="run not found")

        async def stream() -> AsyncIterator[str]:
            for pack in state.get("evidence_packs", []):
                event = {
                    "node": "build_evidence_packs",
                    "claim_id": pack.claim_id,
                    "tokens_before": pack.tokens_before,
                    "tokens_after": pack.tokens_after,
                    "latency_ms": state.get("timings_ms", {}).get("build_evidence_packs"),
                    "error": None,
                }
                yield f"event: state\ndata: {json.dumps(event)}\n\n"
            final = {
                "node": state.get("status"),
                "latency_ms": sum(state.get("timings_ms", {}).values()),
                "error": state.get("error"),
            }
            yield f"event: state\ndata: {json.dumps(final)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/runs/{run_id}/review")
    async def review_run(run_id: str, decision: ReviewDecision) -> dict:
        result = await app.state.workflow.resume(run_id, decision)
        if result.get("status") == "version_conflict":
            raise HTTPException(status_code=409, detail=result["error"])
        if result.get("status") == "invalid_review":
            raise HTTPException(status_code=422, detail=result["error"])
        return _public_state(run_id, result)

    return app


app = create_app()
