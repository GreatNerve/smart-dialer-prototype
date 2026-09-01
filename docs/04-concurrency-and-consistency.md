# 04 — Concurrency and Consistency

## Principles

1. PostgreSQL is the only source of truth.
2. Atomic claim = `SELECT … FOR UPDATE SKIP LOCKED` + compare-and-swap `UPDATE` returning rowcount 1.
3. Every statement inside `in_transaction()` must use `.using_db(conn)`.
4. Provider side effects are idempotent keyed.
5. Crashes are recovered by leases, not by hoping the crashing worker cleans up.

## Tortoise `using_db` rule (critical)

Tortoise ORM does **not** automatically route queries to the connection opened by `in_transaction()`.

```python
# WRONG — lock may be on a different connection
async with in_transaction() as conn:
    agent = await Agent.filter(...).select_for_update(skip_locked=True).first()

# RIGHT
async with in_transaction() as conn:
    agent = await (
        Agent.filter(...)
        .select_for_update(skip_locked=True)
        .using_db(conn)
        .first()
    )
    await Agent.filter(id=agent.id, ...).using_db(conn).update(...)
```

A unit/integration test asserts that reservation under concurrent load yields exactly one winner; a static/convention test greps reservation helpers for `.using_db(`.

## Agent allocation

See [02-agent-state-machine](02-agent-state-machine.md). Sketch:

- Filter `AVAILABLE` for campaign.
- `select_for_update(skip_locked=True)`.
- CAS `state=AVAILABLE, version=V` → `RESERVED, version=V+1, locked_by, lease_expires_at`.

## Borrower allocation

`campaign_contacts` rows:

- Eligible: `next_eligible_at <= now`, `attempts < max_attempts`, not DNC, inside calling window.
- Claim: same SKIP LOCKED + CAS to `IN_PROGRESS` / bind `call_id`.
- On no-answer / fail: increment attempts, set `next_eligible_at = now + backoff(attempts)`, release to retry pool.
- On success/DNC outcome: terminal contact status.

## Call jobs queue (no broker)

```text
call_jobs: id, campaign_id, decision_id, status, locked_by, lease_expires_at, payload
```

Workers:

```sql
SELECT * FROM call_jobs
WHERE status = 'PENDING' AND campaign_id = $1
ORDER BY id
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

Then set `status=IN_PROGRESS`, lease fields, process.

## Pacing leader election

Per pacing tick:

```sql
SELECT pg_try_advisory_xact_lock(hashtext('campaign:' || campaign_id::text));
```

- Winner computes pacing + safety and inserts up to `approved_n` jobs.
- Losers skip pacing this tick; they still consume jobs.
- Transaction ends → lock released. No sticky leader required.

**Defense in depth:** even if two leaders somehow insert jobs, Safety Controller capacity check runs again inside each call-create transaction (`agent-bound in-flight ≤ available + overdial_allowance`).

## Idempotency keys

| Surface | Key |
|---------|-----|
| Provider webhook | `(provider, provider_event_id)` unique |
| Initiate call | `idempotency_key` on call / job (UUID from decision+slot) |
| Job processing | job id claimed once; status machine |

## Optimistic versioning

Agents, calls, contacts carry `version Int`. Updates filter on expected version. Retry with backoff on conflict; fail closed after N attempts.

## Leases, heartbeats, reaper

| Entity | Lease fields |
|--------|--------------|
| Agent RESERVED/DIALING | `locked_by`, `lease_expires_at` |
| Call job IN_PROGRESS | `locked_by`, `lease_expires_at` |
| Call mid-flight (optional) | `worker_id`, `lease_expires_at` |

Owning worker heartbeats (refresh lease). Reaper (single via advisory lock `hashtext('reaper')`):

1. Find expired leases.
2. Release stranded RESERVED agents → AVAILABLE (if agent still online).
3. Re-queue or fail jobs.
4. For calls stuck in INITIATED/RINGING/ANSWERED past deadline: call provider `get_status`; resume projection or mark FAILED/CANCELLED/ABANDONED consistently.

## Stale state

Wall clock is real. Simulated talk/ring durations use `time_scale` compression only for mock provider timers — leases and DB `now()` stay honest.

## Duplicate jobs

Pacing inserts jobs with `decision_id`. Consumers are idempotent per job row. Safety capacity check prevents over-dial even under duplicate decisions.
