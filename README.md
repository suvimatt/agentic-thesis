<h1 align="center">AgenticThesis</h1>

<p align="center">
  <a href="README.md">English</a> | <a href="README_ZH.md">简体中文</a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-Stateful%20Workflow-1C3C3C" alt="LangGraph"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-Async%20API-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-blue.svg" alt="GPL-3.0 license"></a>
  <a href="https://github.com/suvimatt/agentic-thesis/stargazers"><img src="https://img.shields.io/github/stars/suvimatt/agentic-thesis?style=social" alt="GitHub stars"></a>
</p>

<h2 align="center">🚀 Stateful RAG for evidence-first investment thesis monitoring</h2>

AgenticThesis detects how new company disclosures support, weaken, or possibly invalidate an investor's existing thesis. Instead of summarizing one filing once, it produces claim-level cited changes, pauses for Human Review, survives restart, and refuses to overwrite a newer thesis version.

Investment judgment remains with the user. AgenticThesis does not issue Buy / Sell / Hold recommendations.

If this project helps you build more reliable AI research systems, please consider giving it a star. It helps others discover the project and supports further development.

<p align="center">
  <a href="https://github.com/suvimatt/agentic-thesis">
    <img src="https://img.shields.io/badge/%E2%AD%90-Give%20AgenticThesis%20a%20Star-yellow?style=for-the-badge&logo=github" alt="Give AgenticThesis a Star">
  </a>
</p>

## Table of Contents

- [🚀 Quick Start](#-quick-start)
- [Why AgenticThesis](#why-agenticthesis)
- [Investment Philosophy → Engineering Decisions](#investment-philosophy)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Implemented Capabilities](#implemented-capabilities)
- [Verified Results](#verified-results)
- [API Usage](#api-usage)
- [90-Second Verification](#90-second-verification)
- [Deliberate Limits](#deliberate-limits)
- [License](#license)

## 🚀 Quick Start

### 1. Configure model endpoints

Create `~/.agentic-thesis/.env` (or use `.env` in the current directory):

```bash
mkdir -p ~/.agentic-thesis
$EDITOR ~/.agentic-thesis/.env
```

Set these values:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | API key for reranking and structured thesis analysis |
| `OPENAI_BASE_URL` | OpenAI-compatible endpoint for the reasoning model |
| `AGENTIC_THESIS_MODEL` | Reasoning model name |
| `EMBEDDING_API_KEY` | API key for the embedding endpoint |
| `EMBEDDING_BASE_URL` | OpenAI-compatible embedding endpoint |
| `AGENTIC_THESIS_EMBEDDING_MODEL` | Embedding model name |

### 2. Start the application

```bash
uvx --from git+https://github.com/suvimatt/agentic-thesis agentic-thesis serve
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The first start seeds the packaged Apple thesis and filings. Theses, imported disclosures, run history, events, checkpoints, and approved versions persist under `~/.agentic-thesis/` across restarts.

For development and deterministic verification:

```bash
git clone https://github.com/suvimatt/agentic-thesis.git
cd agentic-thesis
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/pytest -q -p no:cacheprovider
```

The test suite uses deterministic retrieval and model substitutes where appropriate, so the core state guarantees can be verified without calling an external model.

## Why AgenticThesis

Most filing assistants answer: *What does this document say?*

AgenticThesis answers a harder, stateful question: *How does this new evidence change what I already believe about the company?*

| One-shot filing assistant | AgenticThesis |
| --- | --- |
| Summarizes one document | Compares new disclosures with a versioned thesis |
| Produces free-form prose | Produces a typed, claim-level `ThesisDelta` |
| Treats chat history as memory | Stores immutable `ThesisSnapshot` versions |
| May return unsupported conclusions | Validates every cited quote against its source |
| Finishes after generation | Requires Human Review before authoritative state changes |
| Restarts from the beginning | Resumes from a SQLite checkpoint |

<a id="investment-philosophy"></a>

## Investment Philosophy → Engineering Decisions

AgenticThesis turns Duan Yongping's "do not invest unless you understand the business" principle into system boundaries, not an investing persona or recommendation engine:

- insufficient or conflicting evidence produces `unknown`, not a forced conclusion;
- user-defined falsifiers make counter-evidence a first-class test, and `possibly_invalidated` requires a matched falsifier;
- the system never issues Buy / Sell / Hold recommendations;
- the user owns the thesis and the final investment judgment;
- new evidence produces only a reviewable `ThesisDelta` proposal; the authoritative `ThesisSnapshot` changes only after explicit Human Review.

## How It Works

```text
ThesisSnapshot v1
→ hybrid retrieval over baseline and new filings
→ token-budgeted EvidencePack per claim
→ structured ThesisDelta
→ citation and falsifier validation
→ Human Review
→ compare-and-swap commit
→ ThesisSnapshot v2 or version_conflict
```

Each claim receives one of four states: `supported`, `weakened`, `possibly_invalidated`, or `unknown`.

## Architecture

[![AgenticThesis system architecture](docs/agentic-thesis-architecture.svg)](docs/agentic-thesis-architecture.html)

The system has one application-owned workflow, not a collection of autonomous agents. LangGraph coordinates six explicit state transitions; deterministic code owns retrieval fusion, Context budgeting, citation integrity, and version commits, while the LLM is limited to semantic reranking and structured thesis comparison.

| Boundary | Responsibility | Implementation |
| --- | --- | --- |
| Interface | Manage theses and disclosures, start work asynchronously, replay progress, and accept review decisions | FastAPI, background `asyncio` tasks, durable SSE |
| Retrieval | Find claim-relevant passages across the filing corpus | deterministic section-labelled fixed-size chunks, BM25, in-process Qdrant vectors, RRF, API rerank |
| Working Context | Give each claim the smallest sufficient, source-addressable evidence | query-conditioned extractive `EvidencePack`, fixed 2,000-token per-claim budget, evidence IDs and source offsets |
| Semantic analysis | Compare every thesis claim with supplied evidence only | API Structured Outputs → typed `ThesisDelta` |
| Integrity gates | Prevent unsupported conclusions or unsafe state changes | quote/source validation, falsifier validation, exact-claim validation, Human Review |
| Durable state | Resume active or paused runs and preserve authoritative thesis history | LangGraph SQLite checkpoints, durable run events, immutable `ThesisSnapshot`s, thesis head |
| Commit | Apply an approved delta only if its base version is still current | SQLite compare-and-swap → `vN+1` or `version_conflict` |

The two checked-in SEC filings contain 97,675 `cl100k_base` tokens after deterministic HTML extraction. A model call never receives the full filings: it receives a per-claim, cited `EvidencePack`. This keeps **Context** (temporary working evidence), **Memory** (versioned thesis), and **Workflow State** (resumable execution) separate.

The editable diagram source is [`docs/agentic-thesis-architecture.html`](docs/agentic-thesis-architecture.html); the README renders its exported SVG.

## Implemented Capabilities

- deterministic SEC HTML extraction, fixed-size chunks with section metadata, character offsets, and stable chunk IDs;
- BM25 + Qdrant local vector retrieval, Reciprocal Rank Fusion, and listwise OpenAI API reranking;
- extractive Context compression with a hard token budget, source coverage, and retained evidence IDs;
- OpenAI Structured Outputs for the four-state `ThesisDelta` contract;
- quote-to-source citation validation; unsupported output is downgraded to `unknown`;
- a six-node LangGraph with Human Review interrupt and SQLite checkpoint/resume;
- immutable thesis snapshots and compare-and-swap conflict protection;
- persistent run history and sequenced SSE replay with `Last-Event-ID` across browser or service restarts;
- multiple isolated theses plus manual HTML/TXT disclosure import;
- async FastAPI, background runs, bounded/timeout-wrapped model calls, checkpoint recovery after shutdown, and live LangGraph events without chain-of-thought;
- a dependency-free product page for thesis/disclosure management, progress, citations, Context compression, and Human Review;
- an installable `agentic-thesis serve` CLI with packaged sample data and a stable user data directory.

## Verified Results

Observed on the checked-in fixtures on 2026-09-01:

| Check | Observed result |
| --- | ---: |
| Tests | 12 passed |
| Clean wheel install | passed outside the repository |
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

Run the live embedding, rerank, Context compression, and Structured Outputs evaluation with:

```bash
.venv/bin/python evals/run_live.py
```

The measured report is written to `evals/live_results.json`; it never contains the API key.

## API Usage

Start and review a run through the API:

```bash
curl -X POST http://localhost:8000/runs \
  -H 'content-type: application/json' \
  -d '{"run_id":"aapl-2024-review","thesis_id":"aapl-primary"}'

curl -N http://localhost:8000/runs/aapl-2024-review/events

curl -X POST http://localhost:8000/runs/aapl-2024-review/review \
  -H 'content-type: application/json' \
  -d '{"action":"approve"}'
```

The browser can also create/list theses, import/list disclosures, list historical runs, and reopen pending reviews. The generated `/docs` page documents the same HTTP API.

## 90-Second Verification

Use the product page for the normal filing → evidence → review path. Then run the single deterministic scenario that proves the two state guarantees that are awkward to stage manually:

```bash
.venv/bin/pytest -vv -p no:cacheprovider \
  tests/test_mvp.py::test_langgraph_resumes_after_restart_and_rejects_stale_commit
```

That scenario pauses a run at Human Review, closes and recreates the workflow on the same SQLite database, resumes the same run ID into Thesis v2, then advances the authoritative head while another run is paused and verifies that its stale approval returns HTTP 409. It uses deterministic fake retrieval and analysis, so it does not call an external model.

## Deliberate limits

- packaged historical Apple filings plus manual HTML/TXT import; no automatic SEC monitor yet;
- Qdrant currently runs in-process; SQLite persists workflow and thesis state;
- no portfolio management, valuation, Multi-Agent roles, scheduler, or distributed queue;
- the five-query eval is intentionally small; no measured cost, throughput, p50, p95, or production-readiness claim.

## License

AgenticThesis is licensed under the [GNU General Public License v3.0](LICENSE).
