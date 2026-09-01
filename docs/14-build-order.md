# 14 — Build Order

Implement in this sequence. Each step should leave tests green for what exists.

1. **Scaffold** — compose, uv, Tortoise config, empty FastAPI app, Makefile.
2. **Models + migrations** — tables from [08-data-model](08-data-model.md).
3. **State machines** — agent/call transition helpers + unit tests.
4. **Reservation** — agent + contact claim with `using_db` + race test.
5. **Safety + pacing types** — `DialRequest`, `ApprovedDialBatch`, progressive strategy, Safety invariants unit tests.
6. **Predictive** — EWMA, warm-up, tail bound, decision persistence.
7. **Allocator + provider port** — in-process fake first.
8. **mock-telco** — HTTP A/B profiles + webhooks to backend.
9. **Webhook ingest** — unique events + rank projection + fuzzer.
10. **Workers** — advisory pacing leader, job consumer, heartbeats, reaper.
11. **API + SSE + chaos**.
12. **Frontend console**.
13. **Failure integration tests**.
14. **Sim CLI + load harness + k6**.
15. **README + demo script**; fill scale table if possible.

## Definition of done

- `docker compose up` runs demo end-to-end.
- Both modes work; Safety can FALLBACK_PROGRESSIVE.
- Five failure scenarios demonstrable.
- Docs match code; ADRs unchanged without new ADR.
