from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models import Agent, Call, CallJob, PacingMetrics
from app.domain.states import AgentState, CallState
from app.settings import get_settings

WINDOW_SECONDS = 15 * 60
WRAP_UP_SECONDS = 8.0  # wall seconds; scaled by campaign elsewhere if needed
EWMA_ALPHA = 0.2


def ewma(prev: float, sample: float, alpha: float = EWMA_ALPHA) -> float:
    return alpha * sample + (1 - alpha) * prev


async def refresh_leases(worker_id: str) -> int:
    """Heartbeat: extend leases owned by this worker."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(seconds=settings.lease_ttl_seconds)
    n = 0
    n += await Agent.filter(
        locked_by=worker_id,
        state__in=[AgentState.RESERVED, AgentState.DIALING, AgentState.CONNECTED],
    ).update(lease_expires_at=expiry)
    n += await CallJob.filter(locked_by=worker_id, status="IN_PROGRESS").update(
        lease_expires_at=expiry
    )
    n += await Call.filter(
        worker_id=worker_id,
        state__in=[
            CallState.RESERVED,
            CallState.INITIATED,
            CallState.RINGING,
            CallState.ANSWERED,
            CallState.CONNECTED,
        ],
    ).update(lease_expires_at=expiry)
    return n


async def roll_metrics_window(metrics: PacingMetrics, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    if metrics.window_started_at is None:
        metrics.window_started_at = now
        await metrics.save()
        return
    age = (now - metrics.window_started_at).total_seconds()
    if age >= WINDOW_SECONDS:
        metrics.abandons_window = 0
        metrics.answered_window = 0
        metrics.window_started_at = now
        await metrics.save()


async def maybe_recover_aggressiveness(metrics: PacingMetrics) -> None:
    """Slowly raise aggressiveness when abandonment is quiet."""
    answered = max(1, metrics.answered_window)
    rate = metrics.abandons_window / answered
    if rate < 0.005 and metrics.aggressiveness < 1.0:
        metrics.aggressiveness = min(1.0, metrics.aggressiveness + 0.05)
        await metrics.save()


async def complete_wrap_ups(now: datetime | None = None) -> int:
    """Move agents past WRAP_UP once wrap duration elapsed (tracked via updated_at)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=WRAP_UP_SECONDS)
    agents = await Agent.filter(state=AgentState.WRAP_UP, updated_at__lte=cutoff)
    n = 0
    for agent in agents:
        await Agent.filter(id=agent.id, state=AgentState.WRAP_UP, version=agent.version).update(
            state=AgentState.AVAILABLE,
            version=agent.version + 1,
            locked_by=None,
            lease_expires_at=None,
            reserved_call_id=None,
        )
        n += 1
    return n
