# 10 — Failure Scenarios

Each scenario maps to an automated test and a chaos-console action.

## 1. Worker crash mid-setup

**Setup:** Agent RESERVED → borrower claimed → call INITIATED → kill worker before heartbeat.

**Expect:**

- Lease expires.
- Reaper releases agent to AVAILABLE (if still online) or reconciles via `get_status`.
- Call reaches FAILED/CANCELLED/COMPLETED consistently with provider truth.
- No double-reservation of the same agent afterward.

**Test:** `tests/integration/test_worker_crash.py`  
**Chaos:** Kill worker button / `POST /api/chaos/kill-worker`

## 2. Provider outage

**Setup:** Flip provider to failing / 100% timeouts.

**Expect:**

- Existing in-flight: reconcile or fail after timeout; agents freed.
- New calls: circuit opens → Safety REJECT / FALLBACK.
- Retries: bounded; idempotency keys prevent duplicate live legs.
- Pacing: desired may be >0 but approved → 0 with `PROVIDER_CIRCUIT_OPEN`.

**Test:** `tests/integration/test_provider_outage.py`  
**Chaos:** Provider failing toggle

## 3. Agent availability cliff

**Setup:** 100 AVAILABLE; drop 40 to OFFLINE within seconds.

**Expect:**

- Next pacing tick (≤ tick interval, default 1s) sees new available count.
- Capacity invariant reduces/rejects overdial.
- In-flight reserved to dropped agents cancelled or abandoned per rules.
- Utilization metrics show reaction within one–two ticks.

**Test:** `tests/integration/test_agent_drop.py`  
**Chaos:** Drop agents

## 4. Duplicate events

**Setup:** Same `event_id` delivered 3×.

**Expect:** One row in `provider_events`; one state transition; HTTP 200 all times.

**Test:** `tests/integration/test_duplicate_events.py` (+ fuzzer)

## 5. Out-of-order events

**Setup:** COMPLETED then ANSWERED then RINGING.

**Expect:** Terminal COMPLETED sticks; later events flagged `out_of_order`; no regression to RINGING.

**Test:** `tests/integration/test_out_of_order_events.py` (+ fuzzer)

## Cross-cutting invariant test

Full simulated campaign: at every tick assert  
`count(agent-bound calls) ≤ count(AVAILABLE+RESERVED+DIALING+CONNECTED agents)`  
with progressive overdial 0; predictive never exceeds Safety-approved capacity.
