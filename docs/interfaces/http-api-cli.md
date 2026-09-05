---
title: HTTP API and CLI
description: Run the self-hosted application and use its key HTTP workflows.
---

# HTTP API and CLI

## CLI

```bash
agentic-thesis serve [--data-dir PATH]
```

The server listens on `127.0.0.1:8000`. Configuration is loaded from the current directory's `.env`, then the selected data directory's `.env`. The default data directory is `~/.agentic-thesis`.

Open the application at `/` and the generated OpenAPI interface at [`/docs`](http://127.0.0.1:8000/docs). The runtime OpenAPI document is the exact endpoint/schema reference for the installed version.

## Key workflow

Create a run for one existing thesis and disclosure:

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H 'content-type: application/json' \
  -d '{"run_id":"aapl-review","thesis_id":"aapl","disclosure_id":"aapl-2026-q2"}'
```

Follow durable events. Reconnect with `Last-Event-ID` to replay only later events:

```bash
curl -N http://127.0.0.1:8000/runs/aapl-review/events
```

Approve after inspecting the proposed delta and cited source text:

```bash
curl -X POST http://127.0.0.1:8000/runs/aapl-review/review \
  -H 'content-type: application/json' \
  -d '{"action":"approve"}'
```

## Monitoring

Configure and check SEC:

```bash
curl -X PUT http://127.0.0.1:8000/theses/aapl/monitor \
  -H 'content-type: application/json' \
  -d '{"cik":"320193","forms":["10-K","10-Q","8-K"],"enabled":true}'

curl -X POST http://127.0.0.1:8000/theses/aapl/sync
```

Configure and check trusted issuer IR pages:

```bash
curl -X PUT http://127.0.0.1:8000/theses/aapl/ir-monitor \
  -H 'content-type: application/json' \
  -d '{"urls":["https://www.example.com/investors"],"enabled":true}'

curl -X POST http://127.0.0.1:8000/theses/aapl/ir-sync
```

Use `/events/{event_id}`, `/events/{event_id}/artifacts`, `/events/{event_id}/failures`, `/collection-attempts`, and `/radar` to inspect what was discovered, preserved, missed, and routed. Fetch raw bytes through `/artifacts/{artifact_id}`.

## Error semantics

| Status | Meaning |
| --- | --- |
| `400` | Invalid protocol input, such as a non-integer `Last-Event-ID` |
| `404` | Requested thesis, disclosure, run, event, or monitor does not exist |
| `409` | Duplicate identity, paused monitor, or stale thesis version |
| `422` | Invalid domain input or edited review |
| `502` | Upstream SEC/IR collection failed; the failed attempt remains recorded |
| `503` | SEC monitoring lacks the required identifying User-Agent |
