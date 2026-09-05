---
title: Python Engine
description: Use AgenticThesisEngine as the supported application interface.
---

# Python Engine

`AgenticThesisEngine` is the supported interface for embedding AgenticThesis in another Python application. Callers provide three bounded model functions; the engine owns local state, retrieval, workflow execution, review, and revision history.

## Open a local engine

```python
from agentic_thesis import AgenticThesisEngine

engine = await AgenticThesisEngine.open_local(
    "./data",
    embed=embed,      # list[str] -> list[list[float]]
    rerank=rerank,    # query + chunks -> ordered chunk IDs
    analyze=analyze,  # thesis + evidence packs -> ThesisDelta
)
```

SQLite stores application state and LangGraph checkpoints; embedded Qdrant stores the rebuildable vector index. Always close the engine when the application stops:

```python
await engine.close()
```

## Run one disclosure through review

```python
from agentic_thesis import (
    DisclosureDocument,
    ReviewDecision,
    ThesisClaim,
    ThesisSnapshot,
)

thesis = ThesisSnapshot(
    thesis_id="example",
    company="Example Inc.",
    version=1,
    claims=[
        ThesisClaim(
            claim_id="retention",
            statement="Customer retention remains durable.",
            rationale="Retention supports recurring cash generation.",
            falsifiers=["Renewal rates decline materially."],
        )
    ],
)
await engine.create_thesis(thesis)

document = DisclosureDocument(
    document_id="example-2026-q2",
    thesis_id=thesis.thesis_id,
    source_id="issuer-q2-results",
    source_date="2026-08-01",
    source_url="https://example.com/investors/q2-results",
    content="<html><body>Renewal rates remained stable.</body></html>",
)
await engine.add_disclosure(document)

paused = await engine.run(
    "example-2026-q2-review",
    thesis.thesis_id,
    document.document_id,
)
assert paused.status == "awaiting_review"

committed = await engine.review(
    paused.run_id,
    ReviewDecision(action="approve"),
)
revisions = await engine.list_revisions(thesis.thesis_id)
```

`run()` registers and executes one disclosure-bound run until it reaches Human Review. For application-controlled streaming, call `start_run()` and iterate `execute_run()` instead.

## Ingest source events

Use `add_disclosure()` for manual HTML/TXT input. Collectors should use `process_event()` to atomically persist a typed `DisclosureEvent`, its `ArtifactInput` values, fetch failures, Radar decision, and optional run registration.

The public Pydantic models are exported from `agentic_thesis`. The executable contract lives in [`tests/test_engine_contract.py`](https://github.com/suvimatt/agentic-thesis/blob/main/tests/test_engine_contract.py); prefer it over examples copied from older releases.

## Conflicts and failures

- Duplicate thesis, disclosure, event, or run identities raise `EngineConflictError`.
- Missing thesis/disclosure/run inputs raise `ValueError`.
- Approval against a stale thesis head raises `EngineConflictError` and preserves both histories.
- Unsupported or invalid evidence is retained as a failure/unknown state rather than silently disappearing.

