import pytest
from httpx import ASGITransport, AsyncClient

from agentic_thesis import (
    AgenticThesisEngine,
    ClaimDelta,
    DeltaStatus,
    DisclosureDocument,
    ReviewDecision,
    ThesisClaim,
    ThesisDelta,
    ThesisSnapshot,
)
from agentic_thesis.api import create_app
from agentic_thesis.rag import HybridRetriever


@pytest.mark.asyncio
async def test_public_engine_runs_local_thesis_lifecycle(tmp_path) -> None:
    thesis = ThesisSnapshot(
        thesis_id="aapl-primary",
        company="Apple Inc.",
        version=1,
        claims=[
            ThesisClaim(
                claim_id="services-margin",
                statement="Services mix supports margins.",
                rationale="Services has higher margins.",
                falsifiers=["Services margin declines."],
            )
        ],
    )
    disclosure = DisclosureDocument(
        document_id="aapl-2024",
        thesis_id=thesis.thesis_id,
        accession="aapl-2024",
        filing_date="2024-09-28",
        source_url="https://example.com/aapl-2024",
        content="<h1>Gross Margin</h1><p>Services gross margin was 73.9 percent.</p>",
    )

    async def embed(texts: list[str]) -> list[list[float]]:
        return HybridRetriever.deterministic_embeddings(texts)

    async def rerank(query, candidates):
        return [candidate.chunk_id for candidate in candidates]

    async def analyze(snapshot, packs):
        return ThesisDelta(
            base_thesis_version=snapshot.version,
            claim_deltas=[
                ClaimDelta(
                    claim_id="services-margin",
                    status=DeltaStatus.SUPPORTED,
                    explanation="Services margin remains high.",
                    evidence_ids=[packs[0].items[0].evidence_id],
                )
            ],
        )

    engine = await AgenticThesisEngine.open_local(
        tmp_path,
        embed=embed,
        rerank=rerank,
        analyze=analyze,
    )
    assert await engine.create_thesis(thesis)
    assert await engine.add_disclosure(disclosure) == 1

    paused = await engine.run("aapl-2024-review", thesis.thesis_id)
    assert paused["__interrupt__"]

    committed = await engine.review(
        "aapl-2024-review", ReviewDecision(action="approve")
    )
    assert committed["status"] == "committed"
    assert committed["thesis"].version == 2
    assert (await engine.get_run("aapl-2024-review"))["status"] == "committed"

    app = create_app(engine)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/theses/{thesis.thesis_id}")
            assert response.status_code == 200
            assert response.json()["version"] == 2

    await engine.close()
