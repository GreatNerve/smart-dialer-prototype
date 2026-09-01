# 06 — Safety Controller

## Role

Sole authority that may approve dials. Consumes `DialRequest` + live `SafetySnapshot`; produces `ApprovedDialBatch` or a reject/fallback decision.

## Capability-token boundary

```python
@dataclass(frozen=True)
class ApprovedDialBatch:
    decision_id: UUID
    campaign_id: UUID
    approved_count: int
    mode: str
    reason_codes: list[str]
    inputs: dict  # audit snapshot
```

- Only `SafetyController.evaluate()` constructs `ApprovedDialBatch`.
- `CallAllocator.execute` type-hints / runtime-checks `ApprovedDialBatch`.
- Pacing package has no symbol that creates this type.
- Test: `pacing` module graph must not import `providers` or `allocation`.

Predictive cannot “turn safety off” — there is no dial path without a batch.

## Decision outcomes

| Outcome | Meaning |
|---------|---------|
| `APPROVE` | `approved_count == desired_count` |
| `REDUCE` | `0 < approved_count < desired_count` |
| `REJECT` | `approved_count == 0`, stay in current mode |
| `FALLBACK_PROGRESSIVE` | Recompute as progressive capacity; tag mode |

## Six invariants (all enforced)

### 1. Hard capacity

```text
agent_bound_after ≤ available_agents + overdial_allowance
```

- Progressive: `overdial_allowance = 0`
- Predictive: allowance may be >0 only as residual already implied by approved predictive policy; typically Safety uses `projected` free agents and still enforces `in_flight_agent_bound ≤ available + reserved_slots` where abandoned risk is separately capped.

Practical rule used in code:

```text
max_new = max(0, available_agents + overdial_allowance - agent_bound_inflight)
approved = min(desired, max_new)
```

### 2. Rolling abandonment ceiling

Window (default 15 minutes wall). Project:

```text
projected_rate = (abandons + expected_new_abandons) / (answered + expected_new_answers)
```

If approving `k` would push projected_rate above ceiling (default 3%), reduce `k` or REJECT.

### 3. Provider circuit breaker

If error rate or p95 initiate latency exceeds thresholds → REJECT or FALLBACK_PROGRESSIVE; open circuit for cooldown.

### 4. Calls-per-second

`approved` clipped so campaign CPS ≤ `max_cps`.

### 5. Slew-rate

`approved` cannot exceed `last_approved * (1 + slew)` + small absolute floor (e.g. +2).

### 6. Degraded-mode kill switch

Campaign or global flag `force_progressive` → always FALLBACK_PROGRESSIVE (or progressive capacity).

## Evaluation order

Apply invariants in order 6 → 3 → 1 → 2 → 4 → 5, threading a running `approved` ceiling downward. Collect all triggered `reason_codes`.

## Abandon path (no free agent on ANSWER)

1. Play safe-harbour message (mock: log + short delay).
2. Hang up; call → `ABANDONED`.
3. Increment abandonment metrics → next Safety tick tightens.

## Audit

Every decision persisted to `safety_decisions` with `decision_id`, inputs, codes, desired vs approved. UI decision log reads this table.
