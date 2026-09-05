---
title: Getting Started
description: Install AgenticThesis, configure model endpoints, and run the self-hosted application.
---

# Getting Started

## Choose a source

Install the latest published package for normal use:

```bash
python -m pip install agentic-thesis
```

The published package can trail the alpha code on `main`. To evaluate the current repository implementation:

```bash
git clone https://github.com/suvimatt/agentic-thesis.git
cd agentic-thesis
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

Do not copy an old version number from a tutorial. Use [PyPI](https://pypi.org/project/agentic-thesis/) for the latest published version and the repository history for unreleased behavior.

## Configure model endpoints

Create `~/.agentic-thesis/.env` or a `.env` file in the directory where you start the application:

```dotenv
# Reasoning and reranking
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
AGENTIC_THESIS_MODEL=gpt-5-mini

# Embeddings
EMBEDDING_API_KEY=your-key
EMBEDDING_BASE_URL=https://api.openai.com/v1
AGENTIC_THESIS_EMBEDDING_MODEL=text-embedding-3-small

# Required only for SEC monitoring
AGENTIC_THESIS_SEC_USER_AGENT="AgenticThesis your-email@example.com"
```

`OPENAI_BASE_URL` is optional when using the default OpenAI API. The other model and embedding credentials are required by the packaged CLI. SEC automated clients must identify themselves; use a real product/name and contact email.

## Start the application

For the published package:

```bash
agentic-thesis serve
```

For alpha development, keep its state separate from an older release:

```bash
.venv/bin/agentic-thesis serve --data-dir ~/.agentic-thesis-v11-alpha
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The default data directory is `~/.agentic-thesis`; the selected directory contains thesis state, run history, checkpoints, artifacts, and the embedded vector index.

## First evidence cycle

1. Create a company thesis in the browser.
2. Write one specific claim and at least one fact that would falsify it.
3. Add a disclosure manually, or configure an SEC/issuer IR monitor.
4. Open the Radar Inbox after a new event is collected.
5. Inspect the exact source evidence and approve, edit, or reject the proposed update.
6. Confirm that only an approved update appears in revision history.

## Verify the checkout without external APIs

```bash
.venv/bin/pytest -q -p no:cacheprovider
```

The deterministic suite replaces external retrieval and model calls where appropriate. It verifies the engine's state and evidence contracts; it does not measure live model accuracy.

