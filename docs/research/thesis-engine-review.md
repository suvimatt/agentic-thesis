# `Srikanth-AD/thesis-engine` fixed-commit review

Reviewed 2026-09-04 against commit [`88920255cf9d7a6684bbbd428eb3f823f4e326c5`](https://github.com/Srikanth-AD/thesis-engine/commit/88920255cf9d7a6684bbbd428eb3f823f4e326c5) (repository HEAD when pinned). Evidence is limited to that commit's source, tests, configuration, and git metadata. README statements below are treated as project claims, not verified outcomes.

## Decision

The repository's useful contribution is a **small, understandable radar product loop**:

> explicit thesis risks and watch events → many cheap signals → one synthesis → urgent or digest notification

AgenticThesis should borrow that product loop, but not its reliability model. `thesis-engine` is a stateless signal aggregator with free-text LLM output; it is not an evidence-addressable thesis engine. Its source breadth is useful inspiration for discovery, while AgenticThesis's typed evidence, citation validation, Human Review, immutable revisions, checkpoint/replay, and version-conflict protection should remain the authoritative core.

## What it actually implements

The executable flow is:

```text
stocks.yaml
  → 13 fetch functions in a six-thread pool
  → one derived keyword-based sustainability layer
  → one large text prompt
  → one Claude response
  → string parsing
  → append-only context/log files and optional email
```

- A single 653-line orchestrator runs bounded parallel fetches with a 90-second overall timeout and records top-level failures per layer ([`analyzer.py#L76-L135`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/analyzer.py#L76-L135)).
- Configuration records portfolio holdings, a prose thesis, explicit `thesis_risks`, and `watch_events` ([`stocks.yaml.example#L24-L49`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/stocks.yaml.example#L24-L49)).
- Source modules cover market data, macro data, RSS/news/attention signals, SEC search metadata, Finnhub insider data, and alternative-data APIs. The entire bundle is flattened into one prompt ([`analyzer.py#L142-L474`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/analyzer.py#L142-L474)).
- The LLM response is free text. `CONTEXT_UPDATE:` lines are appended directly to per-ticker Markdown files before any notification decision, and urgency is detected by substring matching ([`analyzer.py#L481-L529`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/analyzer.py#L481-L529)).
- It provides hourly local scheduling and a GitHub Actions scheduling recipe ([`analyzer.py#L634-L653`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/analyzer.py#L634-L653), [`analyze.yml.example#L14-L60`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/.github/workflows/analyze.yml.example#L14-L60)).

It does **not** implement RAG, PDF/OCR, earnings-call transcripts, official IR page change detection, immutable source artifacts, source versions, claim-level evidence, citation validation, typed model output, Human Review, checkpoint/resume, replay, or thesis version conflict handling. The dependency manifest contains no document or retrieval stack ([`requirements.txt`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/requirements.txt)).

## The parts worth borrowing

| Idea | Why it is useful | Minimal AgenticThesis adaptation |
|---|---|---|
| `thesis_risks` plus `watch_events` | Discovery should be driven by what would change a specific thesis, not only by generic company keywords. | Reuse current claim `falsifiers` as query/routing seeds first. Add a distinct watch-condition model only when a real case cannot be expressed as a falsifier. |
| Bounded connector concurrency and partial success | A broken secondary source should not block an SEC event. | Run explicit collectors independently with timeouts. Persist `FetchFailure`; never convert source outage into “no new evidence.” |
| Deterministic pre-classification | 8-K item codes are routed before title keywords ([`press_releases.py#L23-L67`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/modules/press_releases.py#L23-L67)). | Classify publisher, authority, form/item family, media type, amendment relationship, and exact duplicates before invoking an LLM. |
| Different source cadences | Its always/weekday split recognizes that signals do not share one schedule ([`analyzer.py#L91-L115`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/analyzer.py#L91-L115)). | After a second source is real, store source-specific `next_due_at`/cursor. SEC, IR pages, transcripts, and news should not inherit one global 24-hour cadence. |
| Urgent, digest, and quiet outcomes | It closes the loop with a useful user-facing interruption policy ([`README.md#L177-L191`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/README.md#L177-L191)). | First ship a persisted Radar Inbox with `needs_review`, `digest`, and `ignored`. Add email only after notification demand appears. |
| Human-readable plus machine-readable notification receipts | It writes Markdown and JSONL notification records ([`alerts.py#L315-L390`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/modules/alerts.py#L315-L390)). | A future receipt should reference immutable event, artifact, evidence-span, and revision IDs rather than truncated model prose. |
| Simple deployment recipe | A scheduled single-process job is enough at this scale. | Offer one cron/container recipe later; do not introduce a distributed queue before throughput proves it necessary. |

## README claims not supported by the implementation

- **“14 independent layers”**: only 13 fetchers run concurrently. Sustainability is a keyword scan over already-fetched data, executed afterward ([`analyzer.py#L72-L135`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/analyzer.py#L72-L135), [`analyzer.py#L584-L589`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/analyzer.py#L584-L589), [`sustainability.py#L1-L7`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/modules/sustainability.py#L1-L7)).
- **“Wikipedia recent edits / controversy detection”**: the module reads page-view counts, not edits or revisions ([`README.md#L22-L24`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/README.md#L22-L24), [`wikipedia.py#L29-L58`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/modules/wikipedia.py#L29-L58)).
- **“SEC Form 4 filings”**: the insider module only calls Finnhub; it does not download or parse Form 4 filings ([`insider_trades.py#L33-L61`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/modules/insider_trades.py#L33-L61)).
- **“13F institutional ownership changes”**: it searches for ticker text and counts hits/names. It does not parse holdings tables or compare quarters, and the start date is hard-coded to `2025-10-01` ([`hedge_funds.py#L24-L60`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/modules/hedge_funds.py#L24-L60)).
- **“SEC 8-K radar”**: it searches a seven-day window for ticker text, keeps three metadata hits, does not bind by CIK, retain accession, fetch the primary document/exhibits, or expose a filing-specific URL ([`press_releases.py#L70-L112`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/modules/press_releases.py#L70-L112)).
- **“Around the clock” and immediate alerts**: the supplied cloud schedule is hourly during stated market hours plus one Sunday run, with no durable event cursor ([`analyze.yml.example#L16-L22`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/.github/workflows/analyze.yml.example#L16-L22)).
- **Alert effectiveness and thesis quality**: there is no checked-in retrieval set, model evaluation, alert precision/recall, backtest, or replayable run corpus. The README's “carefully tuned prompt” and detection language are claims, not measured results.

## What not to copy

1. **Do not flatten sources of different authority into one prompt.** SEC, issuer materials, wires, general news, Reddit, Wikipedia attention, and GDELT need typed provenance and distinct evidence permissions.
2. **Do not treat metadata as disclosure evidence.** The 8-K implementation never retrieves the filing body or exhibits; it cannot support a quote, page locator, or claim update.
3. **Do not erase fetch failures.** Several adapters catch all exceptions and return empty results, making “source unavailable” indistinguishable from “no event” ([`press_releases.py#L70-L112`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/modules/press_releases.py#L70-L112)).
4. **Do not copy the financial heuristics.** Item 2.03 debt obligations are labeled “dilution” ([`press_releases.py#L30-L43`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/modules/press_releases.py#L30-L43)); Form 4 award/disposition codes are collapsed into buy/sell sentiment ([`insider_trades.py#L100-L140`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/modules/insider_trades.py#L100-L140)).
5. **Do not let free text mutate thesis history.** `CONTEXT_UPDATE:` is appended before review, while urgency and action are parsed from unconstrained text. AgenticThesis should keep all proposed state non-authoritative until Human Review.
6. **Do not call truncated logs replay.** A run record stores prices and only the first 600 response characters, without input artifacts, prompt/model version, complete output, or evidence IDs ([`analyzer.py#L549-L566`](https://github.com/Srikanth-AD/thesis-engine/blob/88920255cf9d7a6684bbbd428eb3f823f4e326c5/analyzer.py#L549-L566)).
7. **Do not add Buy/Sell/Buy More output.** It conflicts with AgenticThesis's current company-fundamentals boundary and would weaken the human-owned judgment contract.

## Comparison with the current AgenticThesis worktree

| Dimension | `thesis-engine` | AgenticThesis current worktree | Decision |
|---|---|---|---|
| Product surface | Email-first signal monitor | Disclosure-bound thesis revision engine | Borrow the Radar Inbox/notification outcome, not the state model. |
| Thesis model | Prose thesis, risks, watch events | Typed claims, falsifiers, evidence refs, immutable versioned snapshots ([`models.py`](../../src/agentic_thesis/models.py)) | Reuse falsifiers as radar routing inputs first. |
| Source handling | Many ad hoc dicts; metadata/headlines mostly | One thin SEC HTML/manual disclosure path | Expand through `DisclosureEvent + SourceArtifact + EvidenceSpan + FetchFailure`; keep authority explicit. |
| Retrieval | None | BM25/vector fusion, conditional rerank, evidence budget, citation enforcement ([`rag.py`](../../src/agentic_thesis/rag.py)) | Never send the whole cross-source radar bundle to one model prompt. |
| Workflow/state | One process; free-text context append | Typed LangGraph states, checkpoint/resume, Human Review, durable run/revision history, CAS commit ([`workflow.py`](../../src/agentic_thesis/workflow.py)) | Preserve AgenticThesis as the authoritative path. |
| Evaluation | Pure helper tests; no model/retrieval/alert evaluation | Retrieval and thesis-delta fixtures plus recovery/conflict contract tests | Add cross-source fixtures and discovery completeness tests, not generic “layer count” tests. |

## Recommended incorporation into the v1.0 plan

**Now, during SEC completeness:**

- Use current claim falsifiers as watch-topic seeds.
- Add explicit collector failure state and partial-success semantics.
- Deterministically classify SEC form/item family and amendments before relevance analysis.
- Model radar outcomes as `needs_review`, `digest`, or `ignored`; initially expose them in the local Inbox only.

**After official IR/PDF ingestion works:**

- Add source-specific cadences and cursors.
- Add a notification receipt linked to immutable events/artifacts/evidence.
- Add email/digest delivery only if real users ask for off-app interruption.

**Later, and only as leads:**

- Add reliable secondary news, GDELT, attention, or sentiment signals. These may trigger verification but must not independently authorize a thesis revision.

The concise takeaway is: **borrow `risks/watch events → multi-source radar → graded notification`; keep AgenticThesis's evidence-governed engine, and reject the 14-layer flat prompt, silent failures, and automatic free-text state mutation.**

## Verification performed

- Pinned repository HEAD with `git ls-remote`; inspected the detached commit's source, tests, config, and five-commit history.
- `python3 -m compileall -q analyzer.py modules tests`: passed.
- Using the existing AgenticThesis environment, 42 dependency-compatible pure tests passed (`prices`, `congress_trades`, `insider_trades`, `sustainability`, `alerts`).
- Full test collection was **not** claimed: it stopped because that existing environment lacks upstream dependencies `schedule` and `feedparser`. No dependency was installed, and no live API or Claude call was made.
