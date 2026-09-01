# 12 — Scale Analysis

Assume growth: 100 → 1_000 → 10_000 agents on one campaign, multiple workers.

## What breaks first (hypothesis → measure)

| Rank | Bottleneck | Why | Fix direction |
|------|------------|-----|---------------|
| 1 | **Pacing tick read amplification** | Leader aggregates counts/metrics every tick; at 10k agents naive `GROUP BY` + large contact claims contend | Materialized counters table updated transactionally on state change; partition contacts by campaign shard |
| 2 | **SKIP LOCKED claim hotspot** | All workers hit same `AVAILABLE` index / `call_jobs` head | Soft sharding: claim by `agent.id % num_shards = worker_shard`; multiple job partitions |
| 3 | **Webhook ingest single writer** | Burst of provider events updates same call rows / metrics | Batch insert events; async projection workers; per-call hashing to projection shards |
| 4 | **Advisory lock pacing single-threaded** | One pacer per campaign limits dial decision rate | Hierarchical pacing (per skill queue) or token budgets updated continuously instead of tick batches |
| 5 | **Connection pool** | Workers × concurrent transactions | PgBouncer; tune pool; reduce transaction width |

“Add more servers” without fixing claim hotspots and counter aggregation only moves the bottleneck to the database.

## Progressive vs predictive at scale

Predictive increases initiate rate → webhook and provider CPS become limiting before agent row locks if Safety is correct. Circuit breaker and CPS caps protect the provider before Postgres dies.

## Prototype evidence

Fill after `make load`:

| Agents | Tick p95 ms | Reserve/s | Ingest RPS | Notes |
|--------|-------------|-----------|------------|-------|
| 100 | TBD | TBD | TBD | |
| 1_000 | TBD | TBD | TBD | |
| 10_000 | TBD | TBD | TBD | |

Update this table when the harness runs in CI or locally.
