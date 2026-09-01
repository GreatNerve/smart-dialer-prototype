# Final Question

> How would you build a SmartDialer that gets as much of the utilization benefit of predictive dialing as possible, while retaining the deterministic safety characteristics of progressive dialing?

## Answer

**Separate “ambition” from “permission.”**

Predictive pacing is allowed to *propose* overlapping dials using forecasts (answer rate, setup time, talk time) and a probabilistic tail bound. It must never place a call. A Safety Controller — the only component that can mint an `ApprovedDialBatch` — enforces progressive-grade hard rules on every batch:

1. **Capacity CAS** — agent-bound in-flight cannot exceed available agents plus an explicit overdial allowance (zero when behaving progressively).
2. **Abandonment ceiling** — project the effect of this batch on the rolling abandon rate; shrink or reject before dialing.
3. **Fail-closed controls** — provider circuit breaker, CPS, slew limits, and a kill switch that forces progressive math.

Utilization comes from *carefully bounded* overdial during call-setup windows when the forecast says spare agent capacity will exist at connect time — not from removing the safety boundary. When uncertainty is high (warm-up, answer-rate shock, provider illness), Safety clamps approved count to progressive capacity automatically. Feedback from real abandons tightens the next proposals within seconds.

In one line: **predictive proposes, safety disposes, allocator only accepts safety’s token** — so you keep progressive determinism on the path that can create compliance risk, while still harvesting predictive gain when the numbers justify it.
