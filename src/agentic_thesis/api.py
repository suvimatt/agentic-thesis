import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel

from agentic_thesis.models import (
    DisclosureChunk,
    DisclosureDocument,
    ReviewDecision,
    ThesisSnapshot,
)
from agentic_thesis.rag import HybridRetriever, OpenAIModel, chunk_filing
from agentic_thesis.workflow import AgenticThesisWorkflow


class StartRun(BaseModel):
    run_id: str
    thesis_id: str | None = None
    thesis: ThesisSnapshot | None = None
    chunks: list[DisclosureChunk] | None = None


def _public_state(run_id: str, state: dict) -> dict:
    timings = state.get("timings_ms", {})
    return jsonable_encoder(
        {
            "run_id": run_id,
            "status": state.get("status", "running"),
            "thesis": state.get("thesis"),
            "delta": state.get("delta"),
            "evidence_packs": state.get("evidence_packs", []),
            "timings_ms": timings,
            "retrieval_timings_ms": state.get("retrieval_timings_ms", {}),
            "total_ms": round(sum(timings.values()), 3),
            "error": state.get("error"),
        }
    )


async def _default_workflow() -> tuple[AgenticThesisWorkflow, ThesisSnapshot, list[DisclosureChunk]]:
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
    chunks = [
        chunk
        for accession, filing_date, _, source_url in filings
        for chunk in chunk_filing(
            documents[accession],
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
        data_dir / "agentic_thesis.sqlite",
        retriever,
        model.analyze,
    )
    await workflow.create_thesis(thesis)
    for accession, filing_date, _, source_url in filings:
        await workflow.add_disclosure(
            DisclosureDocument(
                document_id=accession,
                thesis_id=thesis.thesis_id,
                accession=accession,
                filing_date=filing_date,
                source_url=source_url,
                content=documents[accession],
            ),
            [chunk for chunk in chunks if chunk.accession == accession],
        )
    return workflow, thesis, chunks


def create_app(workflow: AgenticThesisWorkflow | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if workflow is None:
            app.state.workflow, app.state.thesis, app.state.chunks = await _default_workflow()
        for run in await app.state.workflow.list_runs():
            if run["status"] == "running":
                app.state.run_conditions[run["run_id"]] = asyncio.Condition()
                app.state.run_tasks[run["run_id"]] = asyncio.create_task(
                    execute_run(run["run_id"], resume=True)
                )
        yield
        pending = [task for task in app.state.run_tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if workflow is None:
            await app.state.workflow.close()

    app = FastAPI(title="AgenticThesis", version="0.1.0", lifespan=lifespan)
    if workflow is not None:
        app.state.workflow = workflow
        app.state.thesis = None
        app.state.chunks = None
    app.state.run_tasks = {}
    app.state.run_conditions = {}

    async def publish(run_id: str, event: dict) -> None:
        event = jsonable_encoder(event)
        condition = app.state.run_conditions.setdefault(run_id, asyncio.Condition())
        async with condition:
            await app.state.workflow.append_event(run_id, event)
            condition.notify_all()

    async def execute_run(
        run_id: str,
        thesis: ThesisSnapshot | None = None,
        chunks: list[DisclosureChunk] | None = None,
        *,
        resume: bool = False,
    ) -> None:
        terminal = False
        try:
            updates = (
                app.state.workflow.stream_resume(run_id)
                if resume
                else app.state.workflow.stream_start(run_id, thesis, chunks)
            )
            async for update in updates:
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
        if request.thesis_id:
            thesis = await app.state.workflow.get_thesis(request.thesis_id)
            if thesis is None:
                raise HTTPException(status_code=404, detail="thesis not found")
            chunks = await app.state.workflow.chunks_for_thesis(request.thesis_id)
            if not chunks:
                raise HTTPException(status_code=422, detail="thesis has no disclosures")
        else:
            thesis = request.thesis
            if thesis is None and app.state.thesis is not None:
                thesis = await app.state.workflow.current_snapshot(app.state.thesis)
            chunks = request.chunks or app.state.chunks
        if thesis is None or chunks is None:
            raise HTTPException(status_code=422, detail="thesis and chunks are required")
        existing = app.state.run_tasks.get(request.run_id)
        if existing and not existing.done():
            raise HTTPException(status_code=409, detail="run is already active")
        app.state.run_conditions[request.run_id] = asyncio.Condition()
        if not await app.state.workflow.register_run(request.run_id, thesis):
            raise HTTPException(status_code=409, detail="run already exists")
        app.state.run_tasks[request.run_id] = asyncio.create_task(
            execute_run(request.run_id, thesis, chunks)
        )
        return {"run_id": request.run_id, "status": "running"}

    @app.get("/theses")
    async def list_theses() -> list[ThesisSnapshot]:
        return await app.state.workflow.list_theses()

    @app.post("/theses", status_code=201)
    async def create_thesis(thesis: ThesisSnapshot) -> ThesisSnapshot:
        if thesis.version != 1:
            raise HTTPException(status_code=422, detail="a new thesis must start at version 1")
        if not await app.state.workflow.create_thesis(thesis):
            raise HTTPException(status_code=409, detail="thesis already exists")
        return thesis

    @app.get("/theses/{thesis_id}")
    async def get_thesis(thesis_id: str) -> ThesisSnapshot:
        thesis = await app.state.workflow.get_thesis(thesis_id)
        if thesis is None:
            raise HTTPException(status_code=404, detail="thesis not found")
        return thesis

    @app.get("/disclosures")
    async def list_disclosures(thesis_id: str) -> list[dict]:
        return await app.state.workflow.list_disclosures(thesis_id)

    @app.post("/disclosures", status_code=201)
    async def create_disclosure(document: DisclosureDocument) -> dict:
        if await app.state.workflow.get_thesis(document.thesis_id) is None:
            raise HTTPException(status_code=404, detail="thesis not found")
        chunks = chunk_filing(
            document.content,
            accession=document.accession,
            filing_date=document.filing_date,
            source_url=document.source_url,
        )
        if not chunks:
            raise HTTPException(status_code=422, detail="disclosure contains no text")
        if not await app.state.workflow.add_disclosure(document, chunks):
            raise HTTPException(status_code=409, detail="disclosure already exists")
        return {
            "document_id": document.document_id,
            "thesis_id": document.thesis_id,
            "chunk_count": len(chunks),
        }

    @app.get("/runs")
    async def list_runs(thesis_id: str | None = None) -> list[dict]:
        return await app.state.workflow.list_runs(thesis_id)

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict:
        state = await app.state.workflow.get(run_id)
        if not state:
            raise HTTPException(status_code=404, detail="run not found")
        return _public_state(run_id, state)

    @app.get("/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request) -> StreamingResponse:
        if await app.state.workflow.get_run(run_id) is None:
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
                    events = await app.state.workflow.list_events(run_id, sequence)
                    if not events:
                        run = await app.state.workflow.get_run(run_id)
                        if run["status"] in {
                            "awaiting_review",
                            "committed",
                            "rejected",
                            "failed",
                            "version_conflict",
                        }:
                            return
                        await condition.wait()
                        continue
                for sequence, event in events:
                    yield f"id: {sequence}\nevent: state\ndata: {json.dumps(event)}\n\n"
                    if event["status"] in {"awaiting_review", "committed", "rejected", "failed"}:
                        return

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/runs/{run_id}/review")
    async def review_run(run_id: str, decision: ReviewDecision) -> dict:
        result = await app.state.workflow.resume(run_id, decision)
        if result.get("status") == "version_conflict":
            await publish(
                run_id,
                {
                    "node": "human_review",
                    "status": "version_conflict",
                    "error": result["error"],
                },
            )
            raise HTTPException(status_code=409, detail=result["error"])
        if result.get("status") == "review_conflict":
            raise HTTPException(status_code=409, detail=result["error"])
        if result.get("status") == "invalid_review":
            raise HTTPException(status_code=422, detail=result["error"])
        await publish(
            run_id,
            {
                "node": "human_review",
                "status": result.get("status", "completed"),
                "error": result.get("error"),
            },
        )
        return _public_state(run_id, result)

    return app


app = create_app()
