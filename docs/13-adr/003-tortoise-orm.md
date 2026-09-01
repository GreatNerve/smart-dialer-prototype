# ADR-003: Tortoise ORM

## Status

Accepted

## Context

Need async Python ORM with `select_for_update(skip_locked=True)` and FastAPI lifespan integration.

## Decision

Tortoise ORM 1.1.7 + asyncpg + native migrations. Critical paths always pass `.using_db(conn)` inside transactions. Advisory locks via raw SQL.

## Consequences

- Fast iteration; first-class SKIP LOCKED.
- Footgun if `using_db` omitted — mitigated by docs + tests.
- Hybrid: ORM models + raw SQL for `pg_try_advisory_xact_lock`.
