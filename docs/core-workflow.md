---
title: Core Workflow
description: Understand theses, falsifiers, source events, Radar decisions, evidence, and Human Review.
---

# Core Workflow

## The four core concepts

| Term | Meaning |
| --- | --- |
| Thesis | A versioned record of why a company remains worth owning or following |
| Claim | One falsifiable reason inside that thesis |
| Falsifier | An observable fact that would weaken or break the claim |
| Thesis delta | A proposed, evidence-linked update to the current thesis version |

A new thesis starts at version 1. Every analysis run is bound to exactly one disclosure and one base thesis version.

## From source event to review

```text
configured source
  → disclosure event
  → immutable source artifacts
  → parsed, source-addressable evidence
  → versioned Radar decision
  → claim-by-claim thesis delta
  → Human Review
  → immutable thesis revision
```

### 1. Collect the source

The built-in monitor supports SEC submissions and explicitly configured issuer-owned IR HTML/feed pages. SEC collection retains the filing index, primary report, selected exhibits, and XML data. IR discovery is restricted to configured public HTTPS pages and relevant one-hop same-host documents.

Artifacts are preserved before interpretation. A failed attachment remains visible without discarding the material that was collected successfully.

### 2. Route through Radar

Radar makes a deterministic decision before invoking a model:

| Outcome | Meaning |
| --- | --- |
| `needs_review` | Authoritative, parseable evidence is sufficiently relevant to a claim or falsifier; register an analysis run |
| `digest` | Preserve and display the event, but do not spend a model call |
| `ignored` | Record the routing decision without promoting the event into the working inbox |

The entry retains reason codes, matched claim/falsifier IDs, and a policy version. Replaying the same event does not create duplicate authoritative work.

### 3. Build evidence

Retrieval combines deterministic BM25 and local Qdrant vector results with reciprocal rank fusion. Conditional reranking is called only when the lexical and vector rankings disagree enough to justify it. Context packing retains whole citation spans within the per-claim budget.

Evidence IDs resolve to stored artifact hashes, pages or exact character ranges, and the quoted source text. A forged quote or invalid offset cannot authorize a claim update.

### 4. Compare the thesis

The structured comparison uses four statuses:

- `supported`
- `weakened`
- `possibly_invalidated`
- `unknown`

`unknown` is the correct result when the disclosure does not contain enough evidence. It is not a model failure to avoid inventing a conclusion.

### 5. Keep judgment human-owned

The workflow pauses at Human Review. Approval creates the next immutable `ThesisSnapshot` and a queryable `ThesisRevision`; rejection remains in run history but does not change the thesis. If another review has already advanced the thesis head, compare-and-swap protection returns a version conflict instead of overwriting newer judgment.

## Source authority

Regulator and issuer sources may support a thesis delta when exact evidence is available. User-supplied documents retain their explicit origin. Secondary news belongs in Radar as a verification lead and cannot independently become authoritative thesis history.

