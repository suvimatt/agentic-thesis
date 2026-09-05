---
title: Operations
description: Operate, back up, upgrade, and troubleshoot a self-hosted AgenticThesis instance.
---

# Operations

## Persistent state

`agentic-thesis serve` keeps all local state below the selected `--data-dir`:

- application SQLite data, including theses, events, artifacts, Radar entries, runs, and revisions;
- LangGraph SQLite checkpoints used to resume interrupted work;
- the embedded Qdrant index;
- an optional `.env` file containing local configuration.

The vector index is derived data. The source artifacts, event identities, evidence locators, run history, and thesis snapshots are the authoritative record.

## Back up and restore

1. Stop the local server so SQLite and Qdrant are not being written.
2. Copy the complete data directory to protected storage.
3. Keep `.env` separate if the backup destination is not approved for secrets.
4. Restore the complete directory to the same AgenticThesis schema version.
5. Start the server and verify the thesis, Radar, pending review, and revision lists.

Do not back up only Qdrant. Vectors without application state cannot reconstruct authoritative thesis history.

## Alpha upgrades

Current v1.1 alpha uses a clean schema and intentionally rejects earlier data directories without modifying them. Start it with a fresh directory:

```bash
agentic-thesis serve --data-dir ~/.agentic-thesis-v11-alpha
```

No migration or compatibility promise exists during alpha. Keep an older directory unchanged if you need to run its matching release again.

## SEC access

Set a truthful identifying value before enabling SEC collection:

```dotenv
AGENTIC_THESIS_SEC_USER_AGENT="AgenticThesis your-email@example.com"
```

The scheduler checks whether collection is due once per hour by default and records a successful collection at most once per 24 hours. `AGENTIC_THESIS_SEC_POLL_SECONDS` changes the in-process due-check interval; it is not a distributed scheduling guarantee.

## Security and private data

- Never commit `.env`, API keys, investor notes, or a user data directory.
- Bind the packaged server to localhost unless you add authentication and transport security outside this project.
- Treat issuer pages, filings, uploaded HTML, PDFs, and model output as untrusted input.
- Keep Human Review enabled; model output is never authoritative by itself.
- Artifact downloads use attachment disposition, `application/octet-stream`, and `nosniff` to avoid rendering stored source content in the browser.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| CLI lists missing variables | Populate the required reasoning and embedding credentials in the active `.env` |
| SEC sync returns `503` | Set `AGENTIC_THESIS_SEC_USER_AGENT` and restart the application |
| SEC/IR sync returns `502` | Inspect `/collection-attempts` and per-event failures; a failed check is not treated as “no change” |
| Database is rejected | Use the package version matching that directory, or start the alpha with a fresh directory |
| PDF says `needs_ocr` | Supply an explicit bounded OCR function through the engine; no OCR model is downloaded automatically |
| Approval returns `409` | Reload the latest thesis; another review advanced its authoritative version |

