from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models import ProviderHealth

ERROR_OPEN_THRESHOLD = 0.35
LATENCY_OPEN_MS = 5000.0
CIRCUIT_COOLDOWN_SEC = 30.0
EWMA_ALPHA = 0.3


async def record_provider_attempt(
    provider_name: str,
    *,
    success: bool,
    latency_ms: float,
) -> ProviderHealth:
    health, _ = await ProviderHealth.get_or_create(provider_name=provider_name)
    err = 0.0 if success else 1.0
    health.error_rate_ewma = EWMA_ALPHA * err + (1 - EWMA_ALPHA) * health.error_rate_ewma
    # Track a rough high-water latency as p95 proxy for the prototype
    health.p95_latency_ms = max(
        latency_ms,
        EWMA_ALPHA * latency_ms + (1 - EWMA_ALPHA) * health.p95_latency_ms,
    )
    now = datetime.now(timezone.utc)
    if health.error_rate_ewma >= ERROR_OPEN_THRESHOLD or health.p95_latency_ms >= LATENCY_OPEN_MS:
        health.circuit_open_until = now + timedelta(seconds=CIRCUIT_COOLDOWN_SEC)
    elif health.circuit_open_until and health.circuit_open_until <= now:
        health.circuit_open_until = None
    await health.save()
    return health


async def is_circuit_open(provider_name: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    health = await ProviderHealth.filter(provider_name=provider_name).first()
    if not health or not health.circuit_open_until:
        return False
    return health.circuit_open_until > now
