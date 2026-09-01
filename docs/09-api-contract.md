# 09 — API Contract

Base URL: `http://localhost:8000`

## Campaigns

| Method | Path | Body / notes |
|--------|------|--------------|
| POST | `/api/campaigns` | create `{name, pacing_mode, provider_name, time_scale, ...}` |
| GET | `/api/campaigns` | list |
| GET | `/api/campaigns/{id}` | detail + live counts |
| POST | `/api/campaigns/{id}/start` | status → running |
| POST | `/api/campaigns/{id}/stop` | status → stopped |
| POST | `/api/campaigns/{id}/seed` | `{agents, contacts, answer_rate?, talk_sec?}` |

## Observability

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/campaigns/{id}/snapshot` | agents by state, calls by state, metrics |
| GET | `/api/campaigns/{id}/decisions` | recent safety_decisions |
| GET | `/api/campaigns/{id}/calls` | recent calls |
| GET | `/api/stream?campaign_id=` | **SSE** — `snapshot` + `delta` events |

### SSE event shapes

```json
{"type":"snapshot","data":{ "...full snapshot..." }}
{"type":"delta","data":{"agents":{...},"calls":{...},"last_decision":{...}}}
```

## Chaos

| Method | Path | Effect |
|--------|------|--------|
| POST | `/api/chaos/kill-worker` | signal worker to exit (or set flag) |
| POST | `/api/chaos/provider` | `{provider, profile\|failing:bool}` |
| POST | `/api/chaos/drop-agents` | `{campaign_id, count}` → OFFLINE |
| POST | `/api/chaos/force-progressive` | `{campaign_id, enabled}` |

## Webhooks

| Method | Path |
|--------|------|
| POST | `/webhooks/provider/{provider_name}` |

Body: `{event_id, call_id, type, occurred_at, ...}`. Always 200 on duplicate.

## Simulation / load (CLI preferred)

Also exposed optionally:

- `POST /api/sim/run` — scenario A–D
- `POST /api/load/run` — scale harness (may be CLI-only in prototype)

## Errors

JSON `{"detail": "..."}` with 4xx/5xx. Loading/error states on frontend mirror these.
