<h1 align="center">AgenticThesis</h1>

<p align="center">
  <a href="README.md">English</a> | <a href="README_ZH.md">简体中文</a> | <a href="https://thesis.getsuvi.com/">Documentation</a>
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

AgenticThesis is an open-source AI agent that tests your investment thesis—why you own a stock—against new company disclosures. Every proposed change links to exact source evidence and waits for Human Review before becoming authoritative history.

> **Status:** `main` contains the v1.1 alpha implementation. The latest published package may trail the repository. Alpha schema upgrades intentionally require a fresh data directory.

## Why it exists

You write down why a business deserves to remain in your portfolio or watchlist—and what observable facts would prove each reason wrong. AgenticThesis monitors selected SEC and issuer IR sources, preserves what they published, finds claim-relevant evidence, and proposes a reviewable update.

It does not predict prices, value securities, size positions, or issue Buy/Sell/Hold instructions. The investor owns the judgment.

## A concrete Apple example

An earlier measured run compared three saved beliefs with a new Apple filing:

| Saved belief | New company evidence | Proposed result |
| --- | --- | --- |
| Services improve Apple's business economics | Services gross margin remained materially above Products and Services revenue grew | **Supported** |
| Greater China demand remains steady | Greater China sales declined, driven mainly by lower iPhone and iPad sales | **Possibly invalidated** |
| Supplier concentration will not stop production | Concentration remained disclosed, without evidence that production had stopped | **Weakened** |

Each result retained exact source evidence. None became thesis history until approval. This is an illustrative historical run, not investment advice or a statement about current Apple fundamentals.

## Quick start

Install the latest published package:

```bash
python -m pip install agentic-thesis
```

Configure the reasoning and embedding endpoints in `~/.agentic-thesis/.env`:

```dotenv
OPENAI_API_KEY=your-key
AGENTIC_THESIS_MODEL=gpt-5-mini

EMBEDDING_API_KEY=your-key
EMBEDDING_BASE_URL=https://api.openai.com/v1
AGENTIC_THESIS_EMBEDDING_MODEL=text-embedding-3-small

# Required only for SEC monitoring
AGENTIC_THESIS_SEC_USER_AGENT="AgenticThesis your-email@example.com"
```

Start the self-hosted application:

```bash
agentic-thesis serve
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). For development against current `main`:

```bash
git clone https://github.com/suvimatt/agentic-thesis.git
cd agentic-thesis
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/pytest -q -p no:cacheprovider
.venv/bin/agentic-thesis serve --data-dir ~/.agentic-thesis-v11-alpha
```

See the [5-minute setup](https://thesis.getsuvi.com/getting-started/) for provider URLs, SEC configuration, and the first evidence cycle.

## What v1.1 alpha provides

- **Authoritative collection:** SEC submissions and explicitly trusted issuer IR pages, including selected filing artifacts, PDFs, presentations, and official text transcripts.
- **Immutable provenance:** original bytes, canonical source URLs, SHA-256 fingerprints, parser outcomes, fetch failures, and exact page/character locators.
- **Thesis-aware Radar:** versioned deterministic routing against claims and falsifiers before spending a model call.
- **Bounded evidence:** structure-aware BM25/vector retrieval, conditional reranking, whole-span Context packing, and exact citation validation.
- **Human-owned history:** structured four-state thesis deltas that remain non-authoritative until approval.
- **Recoverable execution:** checkpoint/resume, durable event replay, immutable revisions, and compare-and-swap conflict protection.

## Architecture

[![AgenticThesis system architecture](docs/agentic-thesis-architecture.svg)](https://thesis.getsuvi.com/architecture/)

One application-owned LangGraph coordinates the workflow. Deterministic code owns parsing, retrieval fusion, citation validation, Radar routing, and version commits; model work is limited to embeddings, conditional reranking, and structured thesis comparison.

The same Python distribution exposes:

- `AgenticThesisEngine` for Python applications;
- `agentic-thesis serve` for the local browser UI and FastAPI service.

## Documentation

- [Getting Started](https://thesis.getsuvi.com/getting-started/)
- [Core Workflow](https://thesis.getsuvi.com/core-workflow/)
- [Python Engine](https://thesis.getsuvi.com/interfaces/python-engine/)
- [HTTP API and CLI](https://thesis.getsuvi.com/interfaces/http-api-cli/)
- [Operations](https://thesis.getsuvi.com/operations/)
- [Architecture](https://thesis.getsuvi.com/architecture/)
- [Evaluation and Limits](https://thesis.getsuvi.com/evaluation/)

The runtime FastAPI `/docs` page remains the exact HTTP endpoint/schema reference for the installed version.

## Boundary and license

AgenticThesis maintains company-fundamentals theses. Valuation, portfolio actions, and investment decisions remain outside the engine. Secondary sources may create verification leads but cannot independently authorize thesis history.

Licensed under [GNU Affero General Public License v3.0](LICENSE). Bugs and focused proposals belong in [GitHub Issues](https://github.com/suvimatt/agentic-thesis/issues).

For the complete evidence, operations, and contribution contracts,
use the [documentation site](https://thesis.getsuvi.com/).
