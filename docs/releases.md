---
title: Release Notes
description: Track the currently implemented AgenticThesis release behavior.
---

# Release Notes

## v1.1 alpha.1 — repository implementation

v1.1 alpha turns the earlier SEC-only flow into an authoritative company-information Radar with one recoverable processing path.

- Preserves SEC filing indexes, primary reports, selected exhibits, and XML data with hashes and parser outcomes.
- Traverses SEC submission history, includes selected form families and amendments, and links amendments when reporting-period identity is deterministic.
- Monitors explicitly trusted issuer IR HTML/feed pages and relevant one-hop same-host reports, releases, presentations, and official text transcripts.
- Records replacement, removal, partial fetch failure, PDF parsing, and bounded opt-in OCR states.
- Routes every accepted event through a versioned claim/falsifier Radar policy before model use.
- Atomically commits source artifacts, failures, Radar, and optional run registration with replay-safe IDs.
- Retains exact page/character citations through Human Review and compare-and-swap thesis commits.
- Adds the browser Radar Inbox and SEC/IR configuration surfaces.

The code declares version `1.1.0a1`. Check [PyPI](https://pypi.org/project/agentic-thesis/) before assuming this repository version has been published.

## Earlier milestones

| Version | Product boundary established |
| --- | --- |
| v1.0 alpha | Source-neutral event/artifact ingestion, SEC collection expansion, PDFs, official IR discovery, and Radar |
| v0.9 | Structure-aware disclosure retrieval and exact citation spans |
| v0.8 | One-disclosure-per-run thesis revisions with Human Review and immutable history |
| v0.7 | Public Python engine, self-hosted app, checkpoint/resume, SSE replay, and CAS commits |

Git history and tags are the authoritative detailed changelog. The internal v1.0 and v1.1 execution records remain in the repository but are intentionally excluded from the public documentation build.

