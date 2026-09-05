---
title: Contributing
description: Develop and verify AgenticThesis without weakening its evidence and review guarantees.
---

# Contributing

## Development setup

```bash
git clone https://github.com/suvimatt/agentic-thesis.git
cd agentic-thesis
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/pytest -q -p no:cacheprovider
```

All code, comments, and commit messages must be in English. Keep secrets, user research, generated caches, and local data directories out of Git.

## Change discipline

- Treat executable code, tests, and `pyproject.toml` as the current source of truth.
- Preserve source-addressable evidence, counter-evidence, explicit unknowns, Human Review, recovery, replay, immutable snapshots, and version-conflict protection.
- Use deterministic code for parsing, retrieval fusion, validation, and commits.
- Add an abstraction only when a second real integration requires it.
- Add focused contract tests for public engine changes and recovery/integrity coverage for workflow changes.
- Never claim unmeasured accuracy, latency, throughput, or production readiness.

## Verify code and docs

Install the documentation tools once:

```bash
.venv/bin/python -m pip install -r docs/requirements.txt
```

Then run both contracts:

```bash
.venv/bin/pytest -q -p no:cacheprovider
.venv/bin/python -m mkdocs build --strict
git diff --check
```

Preview locally:

```bash
.venv/bin/python -m mkdocs serve
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the product only when MkDocs is not using that port; MkDocs defaults to [http://127.0.0.1:8000](http://127.0.0.1:8000) as well.

## Documentation rules

- Keep the README as the repository front door; move operational and reference detail here.
- Keep commands executable and link to the runtime FastAPI `/docs` for exact HTTP schemas.
- Update the editable architecture HTML and rendered SVG together when architecture boundaries change.
- Keep execution plans excluded from public navigation.
- English is the authoritative documentation language for this first release; keep the two concise READMEs semantically aligned.

Report bugs or propose focused changes through [GitHub Issues](https://github.com/suvimatt/agentic-thesis/issues).
