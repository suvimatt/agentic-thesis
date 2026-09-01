# AgenticThesis

**A stateful RAG system that detects how new company disclosures support, weaken, or possibly invalidate an investor's existing thesis.**

Most filing assistants summarize one document once. AgenticThesis instead compares a new disclosure with three versioned thesis claims, produces claim-level cited changes, pauses for Human Review, survives restart, and refuses to overwrite a newer thesis version.

AgenticThesis is an evidence-first investment research system. It helps investors maintain a versioned thesis and review how new disclosures change its supporting evidence. Investment judgment remains with the user; the system does not issue Buy / Sell / Hold recommendations.

## Investment Philosophy → Engineering Decisions

AgenticThesis turns Duan Yongping's "do not invest unless you understand the business" principle into system boundaries, not an investing persona or recommendation engine:

- insufficient or conflicting evidence produces `unknown`, not a forced conclusion;
- user-defined falsifiers make counter-evidence a first-class test, and `possibly_invalidated` requires a matched falsifier;
- the system never issues Buy / Sell / Hold recommendations;
- the user owns the thesis and the final investment judgment;
- new evidence produces only a reviewable `ThesisDelta` proposal; the authoritative `ThesisSnapshot` changes only after explicit Human Review.

## Architecture

[![AgenticThesis system architecture](docs/agentic-thesis-architecture.svg)](docs/agentic-thesis-architecture.html)

The system has one application-owned workflow, not a collection of autonomous agents. LangGraph coordinates six explicit state transitions; deterministic code owns retrieval fusion, Context budgeting, citation integrity, and version commits, while the LLM is limited to semantic reranking and structured thesis comparison.

| Boundary | Responsibility | Implementation |
| --- | --- | --- |
| Interface | Start work asynchronously, stream progress, expose state, and accept one review decision | FastAPI, background `asyncio` task, SSE, four endpoints |
| Retrieval | Find claim-relevant passages across the filing corpus | deterministic section-labelled fixed-size chunks, BM25, in-process Qdrant vectors, RRF, API rerank |
| Working Context | Give each claim the smallest sufficient, source-addressable evidence | query-conditioned extractive `EvidencePack`, fixed 2,000-token per-claim budget, evidence IDs and source offsets |
| Semantic analysis | Compare every thesis claim with supplied evidence only | API Structured Outputs → typed `ThesisDelta` |
| Integrity gates | Prevent unsupported conclusions or unsafe state changes | quote/source validation, falsifier validation, exact-claim validation, Human Review |
| Durable state | Resume a paused run and preserve authoritative thesis history | LangGraph SQLite checkpoints, immutable `ThesisSnapshot`s, thesis head |
| Commit | Apply an approved delta only if its base version is still current | SQLite compare-and-swap → `vN+1` or `version_conflict` |

The two checked-in SEC filings contain 97,675 `cl100k_base` tokens after deterministic HTML extraction. A model call never receives the full filings: it receives a per-claim, cited `EvidencePack`. This keeps **Context** (temporary working evidence), **Memory** (versioned thesis), and **Workflow State** (resumable execution) separate.

The editable diagram source is [`docs/agentic-thesis-architecture.html`](docs/agentic-thesis-architecture.html); the README renders its exported SVG.

## What is implemented

- deterministic SEC HTML extraction, fixed-size chunks with section metadata, character offsets, and stable chunk IDs;
- BM25 + Qdrant local vector retrieval, Reciprocal Rank Fusion, and listwise OpenAI API reranking;
- extractive Context compression with a hard token budget, source coverage, and retained evidence IDs;
- OpenAI Structured Outputs for the four-state `ThesisDelta` contract;
- quote-to-source citation validation; unsupported output is downgraded to `unknown`;
- a six-node LangGraph with Human Review interrupt and SQLite checkpoint/resume;
- immutable thesis snapshots and compare-and-swap conflict protection;
- async FastAPI, background runs, bounded/timeout-wrapped model calls, cancellation-safe shutdown, and live LangGraph SSE events with per-claim retrieval/rerank, LLM-node, and cumulative timings but no chain-of-thought;
- a dependency-free product page for progress, claim deltas, citations, Context compression, and Human Review.

## Reproduce the verified path

Python 3.11+ is required.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/pytest -q -p no:cacheprovider
```

Observed on the checked-in fixtures on 2026-09-01:

| Check | Observed result |
| --- | ---: |
| Tests | 9 passed |
| 2023 extracted tokens / chunks | 48,923 / 109 |
| 2024 extracted tokens / chunks | 48,752 / 110 |
| BM25 Recall@5 | 1.00 |
| Deterministic fake-vector Recall@5 | 0.60 |
| RRF hybrid Recall@5 | 1.00 |
| Deterministic fake-rerank Recall@5 | 1.00 |
| Gold evidence retained after compression | 5 / 5 |
| Forged citation | downgraded to `unknown` |
| Restart/resume | committed v2 from the same run ID |
| Stale version | rejected with `version_conflict` / HTTP 409 |

Recall uses the five cases in `evals/gold.json`. The deterministic vector and rerank numbers above verify orchestration and metric calculation.

The checked-in `evals/live_results.json` records a real API run over both filings (219 chunks) using `qwen3.7-text-embedding` and `gpt-5.6-luna`:

| Live check | Observed result |
| --- | ---: |
| BM25 / vector / hybrid / rerank Recall@5 | 1.00 / 0.80 / 1.00 / 1.00 |
| Gold positions, hybrid → rerank | 2→2, 1→1, 2→2, 4→5, 3→3 |
| Gold evidence retained after compression | 5 / 5 |
| Validated claim statuses | supported / possibly_invalidated / weakened |
| Embedding index | 8.73 s |
| Five-query rerank evaluation | 38.17 s |
| Three-claim structured analysis | 16.18 s |

The reranker preserved Recall@5 but did not improve gold position on this five-query set; one case moved from rank 4 to rank 5. These timings are one measured evaluation run, not a latency benchmark or production SLO.

## Run locally

```bash
cp .env.example .env
# Set the API endpoints, models, and keys in .env, then:
.venv/bin/uvicorn agentic_thesis.api:app --env-file .env --port 8000
```

Open `http://127.0.0.1:8000` for the product page. Startup indexes the two fixed filings through the configured embedding endpoint. The same workflow can be driven through the API.

Run the live embedding, rerank, Context compression, and Structured Outputs evaluation with:

```bash
.venv/bin/python evals/run_live.py
```

The measured report is written to `evals/live_results.json`; it never contains the API key.

Start and review a run through the API:

```bash
curl -X POST http://localhost:8000/runs \
  -H 'content-type: application/json' \
  -d '{"run_id":"aapl-2024-review"}'

curl -N http://localhost:8000/runs/aapl-2024-review/events

curl -X POST http://localhost:8000/runs/aapl-2024-review/review \
  -H 'content-type: application/json' \
  -d '{"action":"approve"}'
```

Other endpoints are `GET /runs/{run_id}` and the generated `/docs` OpenAPI page.

## 90-second interview verification

Use the product page for the normal filing → evidence → review path. Then run the single deterministic scenario that proves the two state guarantees that are awkward to stage manually:

```bash
.venv/bin/pytest -vv -p no:cacheprovider \
  tests/test_mvp.py::test_langgraph_resumes_after_restart_and_rejects_stale_commit
```

That scenario pauses a run at Human Review, closes and recreates the workflow on the same SQLite database, resumes the same run ID into Thesis v2, then advances the authoritative head while another run is paused and verifies that its stale approval returns HTTP 409. It uses deterministic fake retrieval and analysis, so it does not call an external model.

## Deliberate limits

- fixed historical Apple filings; no crawler or real-time monitor;
- Qdrant currently runs in-process; SQLite persists workflow and thesis state;
- no portfolio management, valuation, Multi-Agent roles, scheduler, or distributed queue;
- the five-query eval is intentionally small; no measured cost, throughput, p50, p95, or production-readiness claim.
