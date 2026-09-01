import asyncio
import json
import os
from datetime import UTC, datetime
from importlib.resources import files
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
    gold_rank,
    mean_reciprocal_rank,
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
            files("agentic_thesis")
            .joinpath("sample_data", "filings", filename)
            .read_text(errors="ignore"),
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
    rerank_triggers: dict[str, int] = {"rerank": 0, "conditional": 0}
    for mode in ("bm25", "vector", "hybrid", "rerank", "conditional"):
        started = perf_counter()
        results[mode] = {}
        for query in gold:
            if mode in {"rerank", "conditional"}:
                hits, timings = await retriever.search_with_timings(
                    query,
                    limit=5,
                    rerank_policy="always" if mode == "rerank" else "conditional",
                )
                rerank_triggers[mode] += int(timings["rerank_triggered"])
            else:
                hits = await retriever.search(query, mode=mode, limit=5)
            results[mode][query] = [hit.chunk.chunk_id for hit in hits]
        retrieval_ms[mode] = round((perf_counter() - started) * 1_000, 1)

    retained = 0
    for case in cases:
        hits = await retriever.search(case["query"], mode="conditional", limit=5)
        pack = build_evidence_pack(
            "gold-eval",
            case["query"],
            hits,
            token_budget=2_000,
        )
        retained += f'e:{case["gold_chunk_id"]}' in pack.retained_evidence_ids

    thesis = ThesisSnapshot.model_validate_json(
        files("agentic_thesis").joinpath("sample_data", "thesis_v1.json").read_text()
    )
    claim_hits = await asyncio.gather(
        *[
            retriever.search(claim.statement, mode="conditional", limit=6)
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

    def grouped_metrics(field: str) -> dict[str, dict[str, dict[str, float | int]]]:
        grouped: dict[str, dict[str, dict[str, float | int]]] = {}
        for value in sorted({case[field] for case in cases}):
            queries = {case["query"] for case in cases if case[field] == value}
            group_gold = {query: gold[query] for query in queries}
            grouped[value] = {
                mode: {
                    "cases": len(queries),
                    "recall_at_5": recall_at_k(mode_results, group_gold, 5),
                    "mrr": mean_reciprocal_rank(mode_results, group_gold),
                }
                for mode, mode_results in results.items()
            }
        return grouped

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "models": {
            "embedding": model.embedding_model,
            "analysis_and_rerank": model.model,
        },
        "corpus_chunks": len(chunks),
        "gold_cases": len(cases),
        "recall_at_5": {
            mode: recall_at_k(mode_results, gold, 5)
            for mode, mode_results in results.items()
        },
        "mrr": {
            mode: mean_reciprocal_rank(mode_results, gold)
            for mode, mode_results in results.items()
        },
        "by_category": grouped_metrics("category"),
        "by_split": grouped_metrics("split"),
        "rerank_policy": {
            "rule": "rerank when BM25/vector top-1 differ and top-3 overlap is below 2",
            "always_calls": rerank_triggers["rerank"],
            "conditional_calls": rerank_triggers["conditional"],
            "conditional_trigger_rate": rerank_triggers["conditional"] / len(cases),
        },
        "rerank_gold_position": {
            query: {
                "hybrid": gold_rank(results["hybrid"][query], gold_id),
                "rerank": gold_rank(results["rerank"][query], gold_id),
                "conditional": gold_rank(results["conditional"][query], gold_id),
            }
            for query, gold_id in gold.items()
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
