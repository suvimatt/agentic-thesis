---
title: Architecture
description: See how AgenticThesis separates source custody, retrieval, model work, review, and durable state.
---

# Architecture

[![AgenticThesis architecture](agentic-thesis-architecture.svg)](agentic-thesis-architecture.html)

The editable diagram is available as a [standalone HTML source](agentic-thesis-architecture.html).

## Responsibility boundaries

| Layer | Responsibility |
| --- | --- |
| Collection | Discover configured SEC/IR events and preserve exact artifacts before interpretation |
| Parsing | Produce stable, source-addressable sentence, list-item, table-row, and PDF-page spans |
| Radar | Deterministically decide whether an event needs review, belongs in a digest, or is ignored |
| Retrieval | Combine lexical and vector candidates, rerank conditionally, and pack bounded evidence |
| Analysis | Produce a typed claim-by-claim `ThesisDelta` from supplied evidence only |
| Integrity | Validate evidence IDs, exact quotes, offsets, claims, and falsifiers |
| Review | Pause for the investor to approve, edit, or reject the proposed change |
| Commit | Apply an approved delta only when its base thesis version is still current |

## Storage roles

- **Application SQLite** is the authoritative record for events, artifacts, Radar, runs, thesis heads, snapshots, and revisions.
- **Checkpoint SQLite** holds resumable LangGraph execution state separately from application transactions.
- **Embedded Qdrant** stores vectors for local retrieval and can be rebuilt from canonical chunks.
- **Raw artifact bytes and hashes** make every accepted quote traceable to the fetched source version.

## Why one workflow

AgenticThesis has one application-owned LangGraph with six explicit state transitions. It is not a collection of autonomous agents. Retrieval, validation, commits, and conflict protection remain deterministic; models are restricted to embeddings, conditional reranking, and structured comparison.

This keeps Context, Memory, and Workflow State distinct:

- **Context** is the temporary, query-conditioned evidence supplied for one claim.
- **Memory** is the approved, immutable thesis snapshot and revision history.
- **Workflow State** is the recoverable execution record for an active or reviewed run.

## Source boundary

SEC and issuer-owned artifacts may become authoritative evidence. Secondary sources can propose a lead but cannot independently authorize a revision. The model cannot promote a lower-authority source by describing it as official.

