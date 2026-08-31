import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv
from openai import AsyncOpenAI

from agentic_thesis.models import ThesisSnapshot
from agentic_thesis.rag import (
    HybridRetriever,
    OpenAIModel,
    build_evidence_pack,
    chunk_filing,
    enforce_citations,
    recall_at_k,
)


ROOT = Path(__file__).parents[1]


async def main() -> None:
    load_dotenv(ROOT / ".env", override=True)
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY in .env before running the live evaluation.")

    model = OpenAIModel(
        AsyncOpenAI(),
        embedding_client=AsyncOpenAI(
            api_key=os.environ["EMBEDDING_API_KEY"],
            base_url=os.environ["EMBEDDING_BASE_URL"],
        ),
        model=os.getenv("AGENTIC_THESIS_MODEL", "gpt-5-mini"),
        embedding_model=os.getenv(
            "AGENTIC_THESIS_EMBEDDING_MODEL",
            "text-embedding-3-small",
        ),
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
    chunks = [
        chunk
        for accession, filing_date, filename, source_url in filings
        for chunk in chunk_filing(
            (ROOT / "data/filings" / filename).read_text(errors="ignore"),
            accession=accession,
            filing_date=filing_date,
            source_url=source_url,
        )
    ]
    retriever = HybridRetriever(chunks, embed=model.embed, rerank=model.rerank)

    started = perf_counter()
    await retriever.index()
    index_ms = round((perf_counter() - started) * 1_000, 1)

    cases = json.loads((ROOT / "evals/gold.json").read_text())
    gold = {case["query"]: case["gold_chunk_id"] for case in cases}
    results: dict[str, dict[str, list[str]]] = {}
    retrieval_ms: dict[str, float] = {}
    for mode in ("bm25", "vector", "hybrid", "rerank"):
        started = perf_counter()
        results[mode] = {
            query: [
                hit.chunk.chunk_id
                for hit in await retriever.search(query, mode=mode, limit=5)
            ]
            for query in gold
        }
        retrieval_ms[mode] = round((perf_counter() - started) * 1_000, 1)

    retained = 0
    for case in cases:
        hits = await retriever.search(case["query"], mode="rerank", limit=5)
        pack = build_evidence_pack(
            "gold-eval",
            case["query"],
            hits,
            token_budget=2_000,
        )
        retained += f'e:{case["gold_chunk_id"]}' in pack.retained_evidence_ids

    thesis = ThesisSnapshot.model_validate_json((ROOT / "data/thesis_v1.json").read_text())
    claim_hits = await asyncio.gather(
        *[
            retriever.search(claim.statement, mode="rerank", limit=6)
            for claim in thesis.claims
        ]
    )
    packs = [
        build_evidence_pack(
            claim.claim_id,
            claim.statement,
            hits,
            token_budget=2_000,
        )
        for claim, hits in zip(thesis.claims, claim_hits, strict=True)
    ]
    started = perf_counter()
    delta = await model.analyze(thesis, packs)
    analysis_ms = round((perf_counter() - started) * 1_000, 1)
    validated = enforce_citations(delta, packs, thesis)

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "models": {
            "embedding": model.embedding_model,
            "analysis_and_rerank": model.model,
        },
        "corpus_chunks": len(chunks),
        "recall_at_5": {
            mode: recall_at_k(mode_results, gold, 5)
            for mode, mode_results in results.items()
        },
        "gold_retention": {"retained": retained, "total": len(cases)},
        "timings_ms": {
            "embedding_index": index_ms,
            "retrieval_by_mode": retrieval_ms,
            "structured_analysis": analysis_ms,
        },
        "evidence_pack_tokens": {
            pack.claim_id: {
                "before": pack.tokens_before,
                "after": pack.tokens_after,
            }
            for pack in packs
        },
        "validated_thesis_delta": validated.model_dump(mode="json"),
    }
    output = ROOT / "evals/live_results.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"\nSaved {output}")


if __name__ == "__main__":
    asyncio.run(main())
