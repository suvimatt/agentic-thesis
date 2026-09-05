---
title: Evaluation & Limits
description: Review AgenticThesis's reproducible checks, measured results, and deliberate non-claims.
---

# Evaluation & Limits

## Current deterministic checks

Observed on the checked-in fixtures on 2026-09-05:

| Check | Observed result |
| --- | ---: |
| Deterministic test cases | 32 passed: 30 together, 2 scheduler cases separately |
| Wheel build | Passed |
| 2023 / 2024 extracted tokens | 48,777 / 48,903 |
| 2023 / 2024 retrieval windows | 111 / 112 |
| Atomic citation spans / exact reconstruction | 2,547 / 100% |
| Gold retrieval queries | 26: 15 calibration / 11 held-out |
| Thesis-delta cases | 4 across Apple and Microsoft; all four statuses |
| BM25 / fake-vector / hybrid Recall@5 | 0.923 / 0.577 / 0.885 |
| Always / conditional rerank Recall@5 | 0.962 / 0.962 |
| Conditional rerank calls | 15 / 26 |
| Held-out conditional Recall@5 / MRR | 1.00 / 0.720 |

These values come from the checked-in evaluation data and deterministic substitutes. The “fake-vector” result is not an embedding-provider benchmark.

Run the reproducible suite:

```bash
.venv/bin/pytest -q -p no:cacheprovider
```

The focused recovery/conflict scenario is:

```bash
.venv/bin/pytest -vv -p no:cacheprovider \
  tests/test_mvp.py::test_langgraph_resumes_after_restart_and_rejects_stale_commit
```

## Historical live result

`evals/live_results.json` preserves an earlier five-query model-backed run over 219 legacy chunks. It measured 1.00 hybrid and reranked Recall@5, retained all five gold evidence items after compression, and produced valid structured claim statuses. That run predates v0.9 structure-aware chunking and the current 26-case evaluation, so it is historical evidence only.

To generate a new live report with configured endpoints:

```bash
.venv/bin/python evals/run_live.py
```

The script updates `evals/live_results.json`; review the diff before committing it. A single run is not a latency or accuracy benchmark.

## Integrity and recovery coverage

Deterministic tests cover:

- exact quote and offset reconstruction;
- forged evidence downgrade to `unknown`;
- restart/resume into the same run;
- compare-and-swap rejection of stale approval;
- replay-safe event/Radar/run identities;
- partial artifact failure without data loss;
- SEC amendment linking and bounded IR change detection;
- page-addressable PDF evidence and explicit OCR limits.

## Deliberate limits

- IR discovery stops at configured HTTPS pages and relevant one-hop same-host links.
- There is no generic crawler, anti-bot bypass, headless browser, or audio transcription.
- OCR requires an engine-supplied function; the package downloads no model.
- Reliable secondary news is not connected yet.
- Scheduling is one in-process loop, not a queue or distributed service.
- The gold sets remain small and issuer-concentrated.
- There is no measured throughput, p50/p95 latency, production-readiness claim, investment-return claim, price prediction, valuation, or position-sizing recommendation.
