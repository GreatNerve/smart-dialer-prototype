# 11 — Simulation and Load Plan

## Time model

- Wall clock real for DB/leases.
- Mock durations (setup, ring, talk, wrap) divided by `campaign.time_scale` (e.g. 60 → 120s talk ≈ 2s wall).
- Seeded RNG for reproducibility (`SIM_SEED`).

## Scenarios A–D

| Scenario | Answer rate | Avg talk | Notes |
|----------|-------------|----------|-------|
| A | 20% | 120s | Low connect; progressive-like idle |
| B | 50% | 90s | Balanced |
| C | 70% | 180s | High answer; Safety should clamp hard |
| D | Changing | Changing | Mid-run flip answer rate 70%→10% |

CLI:

```bash
make sim SCENARIO=A
make sim SCENARIO=D
```

Record for each run:

- agent utilization (CONNECTED / staffed)
- calls initiated / connected / abandoned
- pacing desired vs approved timeline
- safety reason_code histogram
- provider error counts

Results appendix: `docs/sim-results/` (generated) or printed summary tables in README after runs.

## Load harness

Seed agents: 100 / 1_000 / 10_000; contacts ≫ agents.

Metrics:

- pacing tick duration p50/p95
- agent reservation throughput
- SKIP LOCKED wait / empty-claim rate
- optimistic retry rate
- webhook ingest RPS and latency
- dial E2E latency percentiles

```bash
make load AGENTS=1000
```

## k6

`load/k6_webhook.js` — POST synthetic webhooks at target RPS against `/webhooks/provider/mock_a` with unique and duplicate ids.

```bash
make k6
```
