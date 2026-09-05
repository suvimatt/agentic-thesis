---
title: Evidence-guarded investment theses
description: An open-source engine that keeps investment theses evidence-guarded, human-reviewed, and versioned.
---

<div class="hero" markdown>

# Let every new company report challenge your investment thesis.

AgenticThesis is an open-source AI agent that tests explicit investment theses against new company disclosures. Every proposed change links back to exact source evidence and waits for Human Review before becoming authoritative history.

[Get started in 5 minutes](getting-started.md){ .md-button .md-button--primary }
[Understand the workflow](core-workflow.md){ .md-button }
[View on GitHub](https://github.com/suvimatt/agentic-thesis){ .md-button }

</div>

!!! warning "Alpha software"
    The repository currently contains the v1.1 alpha implementation. Expect clean-schema upgrades and use a fresh data directory when the documented schema version changes.

## Who it is for

AgenticThesis is for self-directed, long-term investors and developers who want a thesis record that can survive new evidence. You state why a business deserves attention and what would prove each reason wrong; the engine monitors selected official sources, proposes evidence-linked updates, and preserves the review trail.

It is also a reusable backend engine. The same Python distribution exposes the `AgenticThesisEngine` interface and the `agentic-thesis serve` self-hosted application.

## What it owns

- discovery of configured SEC and issuer IR events;
- immutable source artifacts with hashes and parser outcomes;
- thesis-aware Radar routing before model use;
- source-addressable evidence and exact citation validation;
- recoverable runs, Human Review, and immutable thesis revisions.

AgenticThesis does **not** value securities, size positions, predict prices, or issue Buy/Sell/Hold instructions. The investor owns the final judgment.

## A concrete example

An earlier measured Apple run compared three beliefs with a new filing:

| Saved belief | New company evidence | Proposed result |
| --- | --- | --- |
| Services improve Apple's business economics | Services gross margin remained materially above Products and Services revenue grew | Supported |
| Greater China demand remains steady | Greater China sales declined, driven mainly by lower iPhone and iPad sales | Possibly invalidated |
| Supplier concentration will not stop production | Concentration remained disclosed, without evidence that production had stopped | Weakened |

Each result retained exact source evidence. None became thesis history until approval. This is an illustrative historical run, not investment advice or a claim about current Apple fundamentals.

## System shape

[![AgenticThesis architecture](agentic-thesis-architecture.svg)](architecture.md)

One application-owned LangGraph coordinates the state transitions. Deterministic code owns parsing, retrieval fusion, citation validation, Radar routing, and version commits; model work is limited to embeddings, conditional reranking, and structured thesis comparison.
