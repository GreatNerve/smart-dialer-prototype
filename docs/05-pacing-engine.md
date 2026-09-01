# 05 — Pacing Engine

## Role

Pure decision function. Inputs are a campaign snapshot; output is `DialRequest`. No DB writes. No provider imports. Cannot mint dials.

```python
@dataclass(frozen=True)
class DialRequest:
    campaign_id: UUID
    desired_count: int
    mode: Literal["progressive", "predictive"]
    reasoning: dict  # machine-readable explanation
```

## Progressive strategy

```text
desired = max(0, available_agents - agent_bound_inflight)
```

`agent_bound_inflight` = calls in RESERVED…CONNECTED that hold or will hold an agent, plus pending jobs already approved.

Overdial allowance for progressive is **0**. Reasoning records counts used.

## Predictive strategy

### Estimators (EWMA)

For each campaign, maintain:

| Symbol | Meaning |
|--------|---------|
| `â` | Answer rate ∈ (0,1) |
| `ŝ` | Mean setup/ring time (seconds, wall) |
| `t̂` | Mean talk time (seconds, wall) |

Update on samples: `x ← α·sample + (1-α)·x` with configurable `α` (default 0.2).

### Warm-up

Until `completed_dial_samples >= min_samples` (default 30), force **progressive** mode in the engine (or emit desired as progressive and tag `warmup=true`). Predictive aggressiveness is never used cold.

### Projection

At dial time `now`, a call started now is expected to connect around `now + ŝ`.

Estimate agents free at connect time:

```text
frees_soon ≈ agents currently in WRAP_UP expected done
           + CONNECTED agents expected to finish by now+ŝ  (using t̂ remaining)
available_now = count(AVAILABLE)
projected_free = available_now + frees_soon
                 - already_ringing_expected_to_answer(â)
```

(Implementation may use a simpler conservative form: `projected_free = available_now` plus a small credit for wrap-ups only — document the exact formula in `reasoning`.)

### Tail bound

Treat connects from `N` new dials as `Binomial(N, â)` or Poisson(`N·â`).

Choose largest integer `N ≥ 0` such that:

```text
P(Connects > projected_free) ≤ target_abandon_probability
```

Default `target_abandon_probability = 0.03` (aligned with abandonment ceiling).

Also cap `N` by:

- pending contact inventory
- slew / CPS left to Safety (engine may soft-cap; Safety hard-enforces)
- configured `max_predictive_batch`

### Feedback trim

If rolling abandonment rate > 50% of ceiling, multiply aggressiveness by `0.5`. If zero abandons and high idle, slowly raise toward 1.0. Store factor in `reasoning`.

## Worked example — “why 17 calls?”

**Snapshot**

- `available_now = 40`
- `ringing = 20`, `â = 0.45` → expected answers from ringing ≈ 9
- `projected_free` after ringing answers ≈ `40 - 9 = 31` (simplified)
- `target_p = 0.03`
- Find max `N` with `P(Binom(N,0.45) > 31) ≤ 0.03`

Using normal approx: mean `μ=0.45N`, var `0.45·0.55·N`. Require roughly:

```text
μ + z·σ ≤ 31,  z ≈ 1.88 for one-sided ~3%
0.45N + 1.88·sqrt(0.2475 N) ≤ 31
```

Solving yields `N ≈ 55` raw; after feedback trim `0.7` and inventory/CPS caps → **17**.

Persisted decision row:

```json
{
  "desired_count": 17,
  "mode": "predictive",
  "a_hat": 0.45,
  "projected_free": 31,
  "target_p": 0.03,
  "raw_n": 55,
  "aggressiveness": 0.7,
  "caps": {"cps": 20, "inventory": 500},
  "why": "tail_bound_trimmed"
}
```

## Mode switch

Campaign config: `pacing_mode = progressive | predictive | auto`.  
`auto` uses progressive during warm-up then predictive.

Safety may still `FALLBACK_PROGRESSIVE` regardless of engine desire.
