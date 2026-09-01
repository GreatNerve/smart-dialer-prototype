# SmartDialer

Functional prototype for the 2026 hiring tech assignment: progressive + predictive pacing, non-bypassable Safety Controller, mock telecom providers, multi-worker concurrency on PostgreSQL, simulation, and an operator/chaos console.

## Quick start

```bash
docker compose up --build -d
# wait ~20s for postgres + API
bash scripts/demo.sh
```

- API: http://localhost:8000/health  
- Console: http://localhost:5173  
- Mock telco: http://localhost:8001/health  

## Docs (design contract)

Start at [docs/00-overview.md](docs/00-overview.md). Full set includes architecture, both state machines, concurrency, pacing math, safety invariants, ADRs, failure scenarios, scale analysis, and [docs/final-question.md](docs/final-question.md).

## Layout

| Path | Role |
|------|------|
| `/docs` | Spec for humans and coding agents |
| `/backend` | FastAPI + Tortoise ORM + workers |
| `/mock-telco` | HTTP providers A/B + webhooks |
| `/frontend` | Vite React chaos console (SSE) |
| `/load` | k6 webhook script |

## Local tests (unit)

```bash
cd backend
pip install -e ".[dev]"   # or: uv pip install -e ".[dev]"
pytest -q tests/unit
```

Postgres integration tests:

```bash
docker compose up -d postgres
export DATABASE_URL=postgres://dialer:dialer@localhost:5432/dialer
export RUN_PG_TESTS=1
pytest -q tests/integration
```

## Simulation & load

```bash
# with DATABASE_URL pointing at postgres
make sim SCENARIO=B
make load AGENTS=100
make k6   # requires k6 + API up
```

## Demo failure scenarios

1. **Worker crash** — Chaos “Kill worker flag” / stop a worker container; leases expire; reaper frees agents.  
2. **Provider outage** — “Provider failing ON”; safety emits `PROVIDER_CIRCUIT_OPEN` / rejects.  
3. **Agent cliff** — “Drop 40 agents”; next tick clamps capacity.  
4. **Duplicates / out-of-order** — use provider profile B (`provider_name: mock_b`) or unit fuzzer.  
5. **Answer-rate shock** — `make sim SCENARIO=D`.

## Pipeline

`Campaign → Pacing Engine → Safety Controller → Call Allocator → Telecom Provider`

Pacing never dials. Only `ApprovedDialBatch` from Safety can reach the allocator.

## What improved in this iteration

- Provider **circuit breaker** now records initiate success/latency and opens on error rate
- Contact **exponential backoff** on failed dials
- Worker **lease heartbeats** + WRAP_UP completion via reaper
- Predictive pacing uses **setup/talk EWMA** and wrap-up/connected agents
- Calling-window gates on contact claim
- SSE **snapshot + delta** events; console falls back to polling with a banner
- Operator UI: pacing sparkline, provider health, KPIs, provider A/B switch, richer chaos
- Snapshot counts via aggregation (with safe fallback)
- Extra unit/integration coverage for circuit, backoff, agent drop
