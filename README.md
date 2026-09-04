<h1 align="center">AgenticThesis</h1>

<p align="center">
  <a href="README.md">English</a> | <a href="README_ZH.md">简体中文</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/agentic-thesis/"><img src="https://img.shields.io/pypi/v/agentic-thesis.svg" alt="PyPI version"></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-Stateful%20Workflow-1C3C3C" alt="LangGraph"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-Async%20API-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue.svg" alt="AGPL-3.0 license"></a>
  <a href="https://github.com/suvimatt/agentic-thesis/stargazers"><img src="https://img.shields.io/github/stars/suvimatt/agentic-thesis?style=social" alt="GitHub stars"></a>
</p>

<h2 align="center">Let every new company report challenge your investment thesis.</h2>

AgenticThesis is an open-source AI agent that tests your investment thesis (why you own a stock) against new company filings—with exact citations, human review, and version history.

**Built for investors who care about the business behind the stock—whatever their investing style.**

You may rely mainly on company research or combine it with price trends, market events, or other methods. AgenticThesis does not ask you to join an investing school. It focuses on one job: checking whether new company evidence supports, weakens, or overturns the reasons you wrote down.

You record those reasons and what would prove each one wrong. AgenticThesis continuously reads official company reports, proposes evidence-linked updates, and shows the exact source text. Nothing enters the versioned thesis history until you review and approve it.

> AgenticThesis does not just tell you what changed at a company. It shows how new evidence changes your thesis—and requires you to approve that change.

> **Status: v1.0 alpha development.** The latest PyPI release remains v0.9.0.

The same Python distribution provides two entry points:

- `agentic-thesis serve` runs the self-hosted application with SQLite and embedded Qdrant;
- `AgenticThesisEngine` is the supported interface for Python applications.

### What does v1.0 alpha.1 actually add?

**v0.9 was closer to a filing reader: you supplied a report, and it checked that report against your reasons for owning the company. v1.0 alpha.1 starts turning it into a radar that watches for new official information.**

- It remembers the last SEC filing it checked and processes only newer filings. If that filing has fallen off the latest list, it searches the older SEC pages to find it;
- it preserves the SEC file listing, official report, important attachments, and XML data exactly as received, together with their source, content fingerprint, and parsing result;
- if one attachment fails to download, the successfully collected material remains usable and the missing attachment and error stay visible;
- each new filing goes through Radar first: readable text starts the existing thesis workflow and waits for Human Review; a filing without readable text is recorded without forcing the AI to reach a conclusion.

In short, **v0.9 handled “read this filing”; v1.0 alpha.1 adds the preceding “find new filings, preserve the complete source record, and decide whether thesis review should start” workflow.**

AgenticThesis lets you write down:

- **what about the company's business makes you willing to keep owning or following it**;
- **what facts would prove each belief wrong**.

It checks the official reports that companies submit to the U.S. regulator. When a new report appears, it compares the new facts with each saved reason, shows the exact original words, and asks you to review the proposed update. If nothing new appears, it does not spend money running an AI analysis.

You remain the decision-maker. AgenticThesis does not decide whether you should buy, sell, or keep a stock.

It focuses on the business behind the stock: how it makes money, why customers buy, its products, costs, advantages, and what could go wrong. It does not predict prices or decide whether today's share price is cheap or expensive.

## A concrete Apple example

An earlier recorded live API run produced these Apple results:

| What you believed | What Apple reported | Result |
| --- | --- | --- |
| Apple's services business helps it keep more money from each sale | For every $100 of sales, Services had $73.90 left after the costs tied directly to those sales, before paying Apple's other bills; Products had $37.20 left, and Services sales grew 13% | **Still looks right** |
| Customers in Greater China will keep buying at a steady level | Sales there fell 8%, mainly because people bought fewer iPhones and iPads | **May be wrong now** |
| Apple can keep making products even when it relies on very few suppliers for some parts | Apple still gets some parts from only one or a few sources, but the report did not show that this had stopped production | **Needs more caution** |

Each result links to the exact words in Apple's report. Nothing changes in your saved record until you approve it.

## Table of Contents

- [A concrete Apple example](#a-concrete-apple-example)
- [🚀 Quick Start](#-quick-start)
- [Python Engine Interface](#python-engine-interface)
- [What AgenticThesis does for you](#what-agenticthesis-does-for-you)
- [Project terms](#project-terms)
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
| `AGENTIC_THESIS_SEC_USER_AGENT` | Your product/name and contact email; required only for SEC monitoring |

SEC requires automated clients to identify themselves. For example:

```dotenv
AGENTIC_THESIS_SEC_USER_AGENT="AgenticThesis your-email@example.com"
```

### 2. Start the application

The latest published release can be started with `uvx agentic-thesis==0.9.0 serve`. Use the development setup below to run the current v1.0 alpha code.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The first start includes a ready-to-use Apple example and two company reports. Your saved reasons, source documents, vector index, checks, pending reviews, and approved updates remain under `~/.agentic-thesis/` after you close and restart the app.

Current `main` uses a clean v1.0 schema and rejects every pre-v1.0 data directory without modifying it. Use a fresh directory:

```bash
agentic-thesis serve --data-dir ~/.agentic-thesis-v10-alpha
```

Add another company in the browser by entering why you own or follow its stock, why that reason matters, and one fact that would prove it wrong. No JSON or schema knowledge is required.

For development and deterministic verification:

```bash
git clone https://github.com/suvimatt/agentic-thesis.git
cd agentic-thesis
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/pytest -q -p no:cacheprovider
```

The test suite uses deterministic retrieval and model substitutes where appropriate, so the core state guarantees can be verified without calling an external model.

## Python Engine Interface

Install the engine from PyPI:

```bash
python -m pip install "agentic-thesis==0.9.0"
```

`open_local` supplies the default SQLite checkpoint/state adapter and persistent embedded Qdrant index. Callers provide the model functions and use domain models exported from `agentic_thesis`:

```python
from agentic_thesis import AgenticThesisEngine, ReviewDecision

engine = await AgenticThesisEngine.open_local(
    "./data",
    embed=embed,
    rerank=rerank,
    analyze=analyze,
)
await engine.create_thesis(thesis)
await engine.add_disclosure(disclosure)
paused = await engine.run(
    "aapl-2024-review",
    thesis.thesis_id,
    disclosure.document_id,
)
committed = await engine.review(
    "aapl-2024-review", ReviewDecision(action="approve")
)
revisions = await engine.list_revisions(thesis.thesis_id)
await engine.close()
```

`run` returns a typed `ThesisRun`, including its bound `disclosure_id`, validated delta, evidence packs, review outcome, and committed version when present. `list_revisions` returns only approved, committed `ThesisRevision` records; rejected runs remain in run history but never become revisions.

The executable contract is [`tests/test_engine_contract.py`](tests/test_engine_contract.py). FastAPI, the browser application, SSE, and the local scheduler are self-host adapters around the same engine; they are not required by engine callers.

## What AgenticThesis does for you

| What usually goes wrong | What AgenticThesis does |
| --- | --- |
| Daily price moves and headlines make you forget why you bought or kept the stock | Keeps a dated history of your original reasons |
| A 100-page company report is too long to compare with every saved reason | Finds the parts relevant to each reason |
| An AI answer sounds certain but may have made something up | Checks every quote against the original report |
| New facts get mixed up with your own decision | Proposes an update and waits for your approval |
| The app or computer restarts during research | Continues from saved progress |

The product helps you check your own reasoning; it does not issue action signals. When the report does not contain enough information, or different facts point in different directions, it says **Not enough information** instead of guessing.

## Project terms

The code uses short internal names for these everyday ideas:

| Internal term | Everyday meaning |
| --- | --- |
| Thesis | Your saved reasons for owning or following a stock |
| Claim | One specific reason you think the company can keep doing well |
| Falsifier | A fact that would prove that reason wrong |
| Thesis delta | A proposed update based on the new report |
| Human Review | You read the original words and decide whether to save the update |

## How It Works

```text
Write down why you own or follow the stock and what would prove each reason wrong
→ AgenticThesis checks the selected official company reports once a day
→ No new report: record the check and stop
→ New report: compare it with every saved reason
→ Show Still looks right / Needs more caution / May be wrong now / Not enough information
→ Link each result to the exact original quotes
→ Wait for you to keep your current record or save the update
```

Under the hood, these four results are stored as `supported`, `weakened`, `possibly_invalidated`, and `unknown`. The reviewable update is a typed `ThesisDelta`; the durable run is a `ThesisRun`; and an approved update creates both the next immutable `ThesisSnapshot` and a queryable `ThesisRevision`.

## Architecture

[![AgenticThesis system architecture](docs/agentic-thesis-architecture.svg)](docs/agentic-thesis-architecture.html)

The system has one application-owned workflow, not a collection of autonomous agents. LangGraph coordinates six explicit state transitions; deterministic code owns retrieval fusion, Context budgeting, citation integrity, and version commits, while the LLM is limited to conditional semantic reranking and structured thesis comparison.

| Boundary | Responsibility | Implementation |
| --- | --- | --- |
| Evidence ingestion | Preserve new official company files before asking AI to interpret them | company submission records (disclosure events), SEC file listings, raw report and attachment bytes, SHA-256 content fingerprints, parser outcomes, download failures, and records of every check |
| Retrieval | Find claim-relevant context within the run's bound disclosure | deterministic structure-aware windows made from intact sentences, list items, and contextualized table rows; claim and falsifier queries; BM25, embedded persistent Qdrant vectors, RRF, and conditional API rerank |
| Working Context | Give each claim the smallest sufficient, source-addressable evidence | query-conditioned `EvidencePack` that packs whole citation spans within a 2,000-token per-claim budget, with span-bound evidence IDs and exact source offsets |
| Semantic analysis | Compare every thesis claim with supplied evidence only | API Structured Outputs → typed `ThesisDelta` |
| Integrity gates | Prevent unsupported conclusions or unsafe state changes | exact citation-span/source validation, falsifier validation, exact-claim validation, Human Review |
| Durable state | Resume active or paused runs and preserve authoritative thesis history | canonical disclosures, LangGraph SQLite checkpoints, durable `ThesisRun` records and events, immutable `ThesisSnapshot`s, queryable `ThesisRevision`s, thesis head |
| Commit | Apply an approved delta only if its base version is still current | SQLite compare-and-swap → `vN+1` or `version_conflict` |

The two checked-in SEC filings contain 97,680 `cl100k_base` tokens after structure-aware extraction. Retrieval uses 223 bounded windows for context, but citations resolve to 2,547 intact atomic spans with exact canonical offsets. A model call never receives a full filing: it receives a per-claim, cited `EvidencePack`. This keeps **Context** (temporary working evidence), **Memory** (versioned thesis), and **Workflow State** (resumable execution) separate.

The editable diagram source is [`docs/agentic-thesis-architecture.html`](docs/agentic-thesis-architecture.html); the README renders its exported SVG.

## Implemented Capabilities

- automatic reading of SEC web filings that removes hidden machine-only tags while preserving sections, complete sentences, lists, and table structure;
- exact preservation of each SEC file listing, official report, important attachment, and XML/XBRL file, together with its source, file type, content fingerprint, and parsing result;
- memory of the last checked filing plus traversal of older SEC pages when needed; one failed attachment gets its own error record without discarding material already collected;
- one saved Radar outcome for every new filing: readable material enters review (`needs_review`), while a filing without readable material is only recorded (`digest`);
- bounded retrieval windows made from intact citation spans rather than token-count slicing, with stable IDs and exact canonical offsets;
- claim-and-falsifier retrieval through BM25 + persistent Qdrant vectors and Reciprocal Rank Fusion; only new windows are embedded, with listwise API reranking only when BM25/vector top-1 differ and top-3 overlap is below 2;
- extractive Context packing with a hard token budget, whole-span selection, source coverage, and retained evidence IDs;
- OpenAI Structured Outputs for the four-state `ThesisDelta` contract;
- exact span-to-source citation validation; unsupported or offset-forged output is downgraded to `unknown`;
- a six-node LangGraph with Human Review interrupt and SQLite checkpoint/resume;
- immutable thesis snapshots and compare-and-swap conflict protection;
- one-disclosure-per-run execution with typed, durable `ThesisRun` outcomes and queryable committed `ThesisRevision` history;
- persistent run history and sequenced SSE replay with `Last-Event-ID` across browser or service restarts;
- multiple isolated theses plus manual HTML/TXT disclosure import;
- one SEC watcher per thesis, selectable report types, duplicate detection, manual “check now,” and a persisted daily check;
- async FastAPI, background runs, bounded/timeout-wrapped model calls, checkpoint recovery after shutdown, and live LangGraph events without chain-of-thought;
- a dependency-free product page with a guided company-reason editor, disclosure management, progress, citations, Context compression, and Human Review;
- an installable `agentic-thesis serve` CLI with packaged sample data and a stable user data directory.

## Verified Results

Observed on the checked-in fixtures on 2026-09-04:

| Check | Observed result |
| --- | ---: |
| Tests | 23 passed |
| Wheel build | passed |
| 2023 extracted tokens / retrieval windows | 48,777 / 111 |
| 2024 extracted tokens / retrieval windows | 48,903 / 112 |
| Atomic citation spans / exact offset reconstruction | 2,547 / 100% |
| Categorized gold queries | 26: 15 calibration / 11 held-out |
| Human-labelled thesis-delta cases | 4 across Apple and Microsoft; all four statuses |
| BM25 / fake-vector / hybrid Recall@5 | 0.923 / 0.577 / 0.885 |
| Always-rerank / conditional-rerank Recall@5 | 0.962 / 0.962 |
| BM25 / vector / hybrid / always / conditional MRR | 0.653 / 0.438 / 0.628 / 0.750 / 0.756 |
| Conditional rerank calls | 15 / 26 |
| Held-out conditional Recall@5 / MRR | 1.00 / 0.720 |
| Forged quote or offset | downgraded to `unknown` |
| Restart/resume | committed v2 from the same run ID |
| Stale version | rejected with `version_conflict` / HTTP 409 |

The 26 cases in `evals/gold.json` cover lexical, numeric, semantic, risk, and regulatory retrieval questions across both Apple filings. The four cases in `evals/delta_gold.json` cover all four delta statuses across Apple and Microsoft, including consecutive Apple disclosures. Deterministic tests validate the dataset and retrieval policy without an external model; they do not claim model accuracy.

The checked-in `evals/live_results.json` preserves an earlier real five-query API run over both filings (219 legacy chunks) using `qwen3.7-text-embedding` and `gpt-5.6-luna`:

| Live check | Observed result |
| --- | ---: |
| BM25 / vector / hybrid / rerank Recall@5 | 1.00 / 0.80 / 1.00 / 1.00 |
| Gold positions, hybrid → rerank | 2→2, 1→1, 2→2, 4→5, 3→3 |
| Gold evidence retained after compression | 5 / 5 |
| Validated claim statuses | supported / possibly_invalidated / weakened |
| Embedding index | 8.73 s |
| Five-query rerank evaluation | 38.17 s |
| Three-claim structured analysis | 16.18 s |

The earlier reranker preserved Recall@5 but did not improve gold position; one case moved from rank 4 to rank 5. This report predates v0.9 structure-aware chunking and the current 26-case retrieval evaluation, so it is historical only: no current live model-quality result is claimed. These timings are one measured run, not a latency benchmark or production SLO.

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
  -d '{"run_id":"aapl-2024-review","thesis_id":"aapl-primary","disclosure_id":"aapl-2024"}'

curl -N http://localhost:8000/runs/aapl-2024-review/events

curl -X POST http://localhost:8000/runs/aapl-2024-review/review \
  -H 'content-type: application/json' \
  -d '{"action":"approve"}'
```

Configure and check an SEC monitor:

```bash
curl -X PUT http://localhost:8000/theses/aapl-primary/monitor \
  -H 'content-type: application/json' \
  -d '{"cik":"320193","forms":["10-K","10-Q","8-K"],"enabled":true}'

curl -X POST http://localhost:8000/theses/aapl-primary/sync
```

The first successful check imports only the latest matching company filing and remembers its unique SEC identifier; it does not suddenly load years of history. Later checks look only for newer filings and search older SEC pages if the remembered filing has fallen off the latest list. `/events`, `/artifacts`, `/collection-attempts`, and `/radar` show what was found, which original files were preserved, which attachments were missed, and why thesis review did or did not start. A failed check is not recorded as a success, so the next check can retry. Every new filing with readable text starts its own `ThesisDelta` workflow and stops at Human Review.

The browser can also create/list theses, import/list disclosures, list historical runs, and reopen pending reviews. The generated `/docs` page documents the same HTTP API.

## 90-Second Verification

Use the product page for the normal filing → evidence → review path. Then run the single deterministic scenario that proves the two state guarantees that are awkward to stage manually:

```bash
.venv/bin/pytest -vv -p no:cacheprovider \
  tests/test_mvp.py::test_langgraph_resumes_after_restart_and_rejects_stale_commit
```

That scenario pauses a run at Human Review, closes and recreates the workflow on the same local persistence set, resumes the same run ID into Thesis v2, then advances the authoritative head while another run is paused and verifies that its stale approval returns HTTP 409. Application state and LangGraph checkpoints use separate SQLite files to avoid writer contention. The test uses deterministic fake retrieval and analysis, so it does not call an external model.

## Deliberate limits

- v1.0 alpha.1 currently watches only SEC EDGAR; company IR pages, PDF/OCR, call transcripts, and news leads are not connected yet;
- the scheduler is one in-process `asyncio` loop that checks due state hourly and automatically performs successful SEC collection at most once per 24 hours; it is not a distributed job system or notification service;
- Qdrant runs embedded and persists vectors under the user data directory; SQLite persists workflow and thesis state;
- no share-price prediction, advice about how much money to put into a company, Multi-Agent roles, distributed scheduler, or queue;
- the retrieval gold set contains 26 Apple questions across two filings; the four-case thesis-delta set adds Microsoft, but broader issuer coverage and a completed current v1.0 alpha live API result are still missing;
- no measured throughput, p50, p95, or production-readiness claim.

## License

AgenticThesis is licensed under the [GNU Affero General Public License v3.0](LICENSE).
