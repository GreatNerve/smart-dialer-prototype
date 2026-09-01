# 00 — Overview

## Problem

Collections agents spend time waiting and dialing numbers that never connect. A SmartDialer improves utilization without violating call-safety / compliance rules.

Two modes:

| Mode | Behaviour | Trade-off |
|------|-----------|-----------|
| **Progressive** | One available agent → at most one agent-bound outbound call | Safe and predictable; agents can idle |
| **Predictive** | Dial before agents free, based on answer-rate estimates | Higher utilization; risk of abandoned connected calls |

An abandoned connected call is a compliance issue. Predictive aggressiveness must never bypass safety.

## What we built

A local, runnable prototype with:

- Progressive Dialer and Predictive Pacing Engine
- Non-bypassable Safety Controller (capability-token boundary)
- Explicit agent and call state machines
- Two mock telecom providers (real HTTP + webhooks) plus a Plivo adapter stub
- Multi-worker concurrency (Postgres `FOR UPDATE SKIP LOCKED`, advisory locks)
- Simulation, chaos console, tests, and load harness

## Pipeline

```
Campaign → Pacing Engine → Safety Controller → Call Allocator → Telecom Provider
                ↑                                      ↓
           Metrics ←←← Rank-monotonic call projection ←← Webhooks
```

The pacing engine returns a `DialRequest`. Only the Safety Controller can mint an `ApprovedDialBatch`. The allocator accepts nothing else.

## Stack

| Layer | Choice | Why |
|-------|--------|-----|
| API / workers | Python 3.12, FastAPI | Async I/O for webhooks and worker loops |
| ORM | Tortoise ORM 1.1.7 + asyncpg | Native `select_for_update(skip_locked=True)`, FastAPI integration |
| DB | PostgreSQL 16 | Single source of truth; advisory locks; SKIP LOCKED |
| Frontend | Vite + React + TypeScript | Operator / chaos console over SSE |
| Mock telco | Separate FastAPI service | Real HTTP + webhook path |
| Package mgmt | `uv` | Fast, reproducible |

No Redis, no Kafka, no cache. Divergent cache/DB state is a class of bugs we refuse to introduce.

## Repo layout

```
/docs          Spec set (this folder) — contract for implementers
/backend       Dialer API, workers, domain, pacing, safety
/mock-telco    Provider simulator (profiles A and B)
/frontend      Operator console
docker-compose.yml
Makefile
README.md
```

## Reading order

1. [01-architecture](01-architecture.md)
2. [02-agent-state-machine](02-agent-state-machine.md) / [03-call-state-machine](03-call-state-machine.md)
3. [04-concurrency-and-consistency](04-concurrency-and-consistency.md)
4. [05-pacing-engine](05-pacing-engine.md) / [06-safety-controller](06-safety-controller.md)
5. [07-provider-abstraction](07-provider-abstraction.md) → [09-api-contract](09-api-contract.md)
6. [10-failure-scenarios](10-failure-scenarios.md) → [12-scale-analysis](12-scale-analysis.md)
7. [13-adr/](13-adr/) · [14-build-order](14-build-order.md) · [final-question](final-question.md)

## Evaluation map

| Rubric area | Where it lives |
|-------------|----------------|
| System design 20% | 01, ADRs |
| Distributed systems 15% | 04, 10 |
| Progressive 10% | 05 |
| Predictive 15% | 05, simulation |
| Safety 15% | 06, capability token |
| Failure handling 10% | 10 |
| Testing & performance 10% | 11, 12, tests/ |
| Code quality & docs 5% | this set + README |
