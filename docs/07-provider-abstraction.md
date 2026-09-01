# 07 — Provider Abstraction

## Port

```python
class TelecomProvider(Protocol):
    name: str

    async def initiate_call(
        self, *, to_number: str, from_number: str,
        webhook_url: str, idempotency_key: str, metadata: dict,
    ) -> InitiateResult: ...

    async def hangup(self, provider_call_id: str) -> None: ...

    async def get_status(self, provider_call_id: str) -> CallStatus: ...

    async def play_safe_harbour(self, provider_call_id: str) -> None: ...
```

Dialer code depends only on this port.

## Mock profiles (HTTP service `mock-telco`)

| Profile | Behaviour |
|---------|-----------|
| **A** | Fast setup, low failure (~1%), ordered single events |
| **B** | Slow / jittery, timeouts (~10%), duplicate webhooks, out-of-order delivery |

Config selects profile per campaign or chaos endpoint flips live behaviour.

### Event types emitted

`initiated`, `ringing`, `answered`, `completed`, `failed`, `cancelled` (mapped to call states).

## In-process fake

Same port; deterministic RNG seed; invokes ingest callback directly (no HTTP). Used by unit/integration tests.

## Plivo adapter

`PlivoProvider` implements the port against Plivo REST API. Disabled unless `PLIVO_AUTH_ID` / `PLIVO_AUTH_TOKEN` set. No credentials required for default demo. Documents webhook signature verification for production.

## Circuit breaker

Tracked in DB / memory per provider name: consecutive failures, latency samples. Safety Controller reads health snapshot.

## Dialer ignorance

Allocator never branches on “if provider B”. Retries/timeouts are generic; messy behaviour is absorbed by idempotent ingest + rank projection.
