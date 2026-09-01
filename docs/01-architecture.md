# 01 — Architecture

## Component view

```mermaid
flowchart TB
  subgraph frontend [Frontend Vite React]
    Console[Operator Chaos Console]
  end

  subgraph backend [Backend FastAPI]
    API[REST + SSE API]
    Workers[Dialer Workers]
    Pacing[Pacing Engine]
    Safety[Safety Controller]
    Allocator[Call Allocator]
    Ingest[Webhook Ingest]
    Reaper[Lease Reaper]
  end

  subgraph mock [Mock Telco]
    ProvA[Provider A fast]
    ProvB[Provider B messy]
  end

  PG[(PostgreSQL)]

  Console -->|HTTP + SSE| API
  API --> PG
  Workers --> Pacing
  Pacing -->|DialRequest| Safety
  Safety -->|ApprovedDialBatch| Allocator
  Allocator -->|initiate_call| ProvA
  Allocator -->|initiate_call| ProvB
  ProvA -->|webhooks| Ingest
  ProvB -->|webhooks| Ingest
  Ingest --> PG
  Workers --> PG
  Reaper --> PG
  Allocator --> PG
```

## Request / dial sequence

```mermaid
sequenceDiagram
  participant W as Worker leader
  participant P as Pacing Engine
  participant S as Safety Controller
  participant A as Call Allocator
  participant DB as PostgreSQL
  participant T as Telecom Provider

  W->>DB: pg_try_advisory_xact_lock(campaign_id)
  W->>DB: read agent counts, metrics, in-flight
  W->>P: compute DialRequest(desired_n, reasoning)
  P-->>W: DialRequest
  W->>S: evaluate(DialRequest, Snapshot)
  S-->>W: ApprovedDialBatch(approved_n, decision_id, codes)
  loop approved_n times
    W->>DB: insert call_jobs PENDING
  end

  Note over W: Any worker claims jobs
  W->>DB: SELECT FOR UPDATE SKIP LOCKED call_jobs
  W->>DB: reserve agent + claim borrower CAS
  W->>A: execute(ApprovedDialBatch, job)
  A->>T: initiate_call
  T-->>A: provider_call_id
  A->>DB: call INITIATED
```

## Webhook / projection sequence

```mermaid
sequenceDiagram
  participant T as Provider
  participant I as Webhook Ingest
  participant DB as PostgreSQL
  participant Proj as Rank Projection

  T->>I: POST /webhooks/provider/{name}
  I->>DB: INSERT provider_events UNIQUE(provider, event_id)
  alt duplicate
    DB-->>I: conflict → 200 no-op
  else new
    I->>Proj: apply(event)
    Proj->>DB: CAS call.state if rank(new) > rank(old)
    Proj->>DB: update agent / metrics on CONNECTED / terminal
  end
```

## Process topology (docker-compose)

| Service | Role |
|---------|------|
| `postgres` | Single source of truth |
| `backend` | API + SSE (uvicorn) |
| `worker` | N replicas: pacing leader election, job claim, heartbeats |
| `mock-telco` | HTTP provider + outbound webhooks |
| `frontend` | Vite static / dev server |

Workers are identical. Leadership for pacing is per-tick via `pg_try_advisory_xact_lock`. Job consumption is fully symmetric via `SKIP LOCKED`.

## Package boundaries (backend)

```
app/
  domain/       models, state machines, reservation helpers
  pacing/       DialRequest only — NO imports of providers or allocator
  safety/       evaluates DialRequest → ApprovedDialBatch
  allocation/   accepts ApprovedDialBatch only
  providers/    TelecomProvider port + adapters
  workers/      pacing tick, job consumer, reaper
  api/          REST, SSE, chaos, webhooks
  db/           Tortoise config, clock port
```

Import rule: `pacing` must not import `providers`, `allocation`, or write APIs. Enforced by test.

## Why this shape

- **One DB** — no cache coherence interviews to lose.
- **Capability token** — predictive cannot dial around safety.
- **Advisory lock + SKIP LOCKED** — coordinates N workers without a broker.
- **Separate mock-telco** — exercises real webhook idempotency.
- **SSE** — one-way live UI is enough; no WebSocket lifecycle.

## What we deliberately did not build

Kafka, Redis, microservices split for Safety Controller, ML models, real SSR frontend, multi-region failover.
