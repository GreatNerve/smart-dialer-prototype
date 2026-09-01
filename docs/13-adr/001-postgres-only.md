# ADR-001: PostgreSQL as sole source of truth

## Status

Accepted

## Context

Multi-worker dialer needs atomic agent/borrower allocation and durable call state. Cache+DB invites “which wins?” ambiguity under interview pressure.

## Decision

Use PostgreSQL only. No Redis cache for agent state. Job queue is a Postgres table with `FOR UPDATE SKIP LOCKED`.

## Consequences

- Simpler correctness story.
- Throughput ceiling is Postgres — acceptable for prototype; scale plan documents sharding of claims.
- Cannot offload ephemeral pacing counters to Redis without a new ADR.
