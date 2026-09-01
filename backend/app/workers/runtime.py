from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from tortoise.transactions import in_transaction

from app.allocation.allocator import CallAllocator
from app.domain.metrics import complete_wrap_ups, maybe_recover_aggressiveness, roll_metrics_window
from app.domain.models import (
    Agent,
    Call,
    CallJob,
    Campaign,
    CampaignContact,
    PacingMetrics,
    ProviderHealth,
    SafetyDecision,
)
from app.domain.states import AGENT_BOUND_CALL_STATES, AgentState, CallState
from app.pacing.engine import compute_dial_request
from app.pacing.types import CampaignSnapshot
from app.providers.health import is_circuit_open
from app.providers.registry import get_provider
from app.safety.controller import ApprovedDialBatch, SafetyController, SafetySnapshot
from app.settings import get_settings


def _stable_lock_key(key: str) -> int:
    import hashlib
    import struct

    digest = hashlib.sha256(key.encode()).digest()[:8]
    return struct.unpack(">q", digest)[0] & 0x7FFFFFFF


async def try_advisory_lock(conn, key: str) -> bool:
    lock_key = _stable_lock_key(key)
    _, rows = await conn.execute_query(
        "SELECT pg_try_advisory_xact_lock($1) AS ok", [lock_key]
    )
    if not rows:
        return False
    row = rows[0]
    return bool(row[0] if isinstance(row, (list, tuple)) else row.get("ok"))


async def build_snapshot(campaign: Campaign) -> CampaignSnapshot:
    available = await Agent.filter(
        campaign_id=campaign.id, state=AgentState.AVAILABLE
    ).count()
    wrap_ups = await Agent.filter(
        campaign_id=campaign.id, state=AgentState.WRAP_UP
    ).count()
    connected = await Agent.filter(
        campaign_id=campaign.id, state=AgentState.CONNECTED
    ).count()
    inflight = await Call.filter(
        campaign_id=campaign.id, state__in=list(AGENT_BOUND_CALL_STATES)
    ).count()
    pending = await CallJob.filter(campaign_id=campaign.id, status="PENDING").count()
    ringing = await Call.filter(
        campaign_id=campaign.id, state=CallState.RINGING
    ).count()
    inventory = await CampaignContact.filter(
        campaign_id=campaign.id, status="eligible", dnc=False
    ).count()
    metrics, _ = await PacingMetrics.get_or_create(campaign_id=campaign.id)
    await roll_metrics_window(metrics)
    await maybe_recover_aggressiveness(metrics)
    return CampaignSnapshot(
        campaign_id=campaign.id,
        available_agents=available,
        agent_bound_inflight=inflight,
        pending_jobs=pending,
        ringing=ringing,
        answer_rate_ewma=metrics.answer_rate_ewma,
        setup_sec_ewma=metrics.setup_sec_ewma,
        talk_sec_ewma=metrics.talk_sec_ewma,
        samples=metrics.samples,
        aggressiveness=metrics.aggressiveness,
        min_warmup_samples=campaign.min_warmup_samples,
        target_abandon_prob=campaign.target_abandon_prob,
        pacing_mode=campaign.pacing_mode,
        force_progressive=campaign.force_progressive,
        contact_inventory=inventory,
        abandons_window=metrics.abandons_window,
        answered_window=metrics.answered_window,
        wrap_up_agents=wrap_ups,
        connected_agents=connected,
    )


async def pacing_tick(campaign_id: UUID, worker_id: str) -> dict | None:
    settings = get_settings()
    async with in_transaction() as conn:
        ok = await try_advisory_lock(conn, f"campaign:{campaign_id}")
        if not ok:
            return None
        campaign = await Campaign.filter(id=campaign_id).using_db(conn).first()
        if campaign is None or campaign.status != "running":
            return None

        snap = await build_snapshot(campaign)
        request = compute_dial_request(snap)
        circuit_open = await is_circuit_open(campaign.provider_name)
        metrics, _ = await PacingMetrics.get_or_create(campaign_id=campaign.id)
        safety_snap = SafetySnapshot(
            available_agents=snap.available_agents,
            agent_bound_inflight=snap.agent_bound_inflight,
            pending_jobs=snap.pending_jobs,
            overdial_allowance=campaign.overdial_allowance,
            abandon_rate_ceiling=campaign.abandon_rate_ceiling,
            abandons_window=snap.abandons_window,
            answered_window=snap.answered_window,
            max_cps=campaign.max_cps,
            slew_factor=campaign.slew_factor,
            last_approved=metrics.last_approved,
            force_progressive=campaign.force_progressive,
            provider_circuit_open=circuit_open,
            now=datetime.now(timezone.utc),
            tick_seconds=settings.pacing_tick_seconds,
        )
        batch = SafetyController().evaluate(request, safety_snap)
        await SafetyDecision.create(
            id=batch.decision_id,
            campaign_id=campaign.id,
            desired_count=request.desired_count,
            approved_count=batch.approved_count,
            outcome=batch.outcome,
            mode=batch.mode,
            reason_codes=list(batch.reason_codes),
            inputs=batch.inputs,
        )
        for _ in range(batch.approved_count):
            await CallJob.create(
                id=uuid4(),
                campaign_id=campaign.id,
                decision_id=batch.decision_id,
                status="PENDING",
            )
        metrics.last_approved = batch.approved_count
        await metrics.save()
        return {
            "desired": request.desired_count,
            "approved": batch.approved_count,
            "outcome": batch.outcome,
            "codes": list(batch.reason_codes),
            "decision_id": str(batch.decision_id),
            "mode": batch.mode,
            "reasoning": request.reasoning,
        }


async def claim_job(campaign_id: UUID, worker_id: str) -> CallJob | None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    async with in_transaction() as conn:
        job = (
            await CallJob.filter(campaign_id=campaign_id, status="PENDING")
            .select_for_update(skip_locked=True)
            .using_db(conn)
            .order_by("id")
            .first()
        )
        if job is None:
            return None
        await CallJob.filter(id=job.id).using_db(conn).update(
            status="IN_PROGRESS",
            locked_by=worker_id,
            lease_expires_at=now + timedelta(seconds=settings.lease_ttl_seconds),
        )
        job.status = "IN_PROGRESS"
        return job


async def process_job(job: CallJob, worker_id: str) -> None:
    campaign = await Campaign.filter(id=job.campaign_id).first()
    if campaign is None:
        await CallJob.filter(id=job.id).update(status="DONE")
        return
    decision = await SafetyDecision.filter(id=job.decision_id).first()
    if decision is None:
        await CallJob.filter(id=job.id).update(status="DONE")
        return

    batch = ApprovedDialBatch.from_persisted(
        decision_id=decision.id,
        campaign_id=campaign.id,
        mode=decision.mode,
        outcome=decision.outcome,
        reason_codes=decision.reason_codes,
        inputs=decision.inputs,
        slot_count=1,
    )

    inflight = await Call.filter(
        campaign_id=campaign.id,
        state__in=list(AGENT_BOUND_CALL_STATES),
    ).count()
    available = await Agent.filter(
        campaign_id=campaign.id, state=AgentState.AVAILABLE
    ).count()
    allowance = 0 if batch.mode == "progressive" else campaign.overdial_allowance
    if batch.mode == "progressive" and available <= 0:
        await CallJob.filter(id=job.id).update(status="DONE")
        return
    if inflight >= available + allowance and batch.mode == "progressive":
        await CallJob.filter(id=job.id).update(status="DONE")
        return
    if await is_circuit_open(campaign.provider_name):
        await CallJob.filter(id=job.id).update(status="DONE")
        return

    provider = get_provider(campaign.provider_name)
    allocator = CallAllocator(provider)
    await allocator.execute_one(
        batch,
        campaign=campaign,
        worker_id=worker_id,
        now=datetime.now(timezone.utc),
    )
    await CallJob.filter(id=job.id).update(status="DONE")


async def reaper_once() -> int:
    now = datetime.now(timezone.utc)
    fixed = 0
    async with in_transaction() as conn:
        ok = await try_advisory_lock(conn, "reaper")
        if not ok:
            return 0
        expired_agents = await Agent.filter(
            lease_expires_at__lt=now,
            state__in=[AgentState.RESERVED, AgentState.DIALING],
        ).using_db(conn)
        for agent in expired_agents:
            await Agent.filter(id=agent.id).using_db(conn).update(
                state=AgentState.AVAILABLE,
                locked_by=None,
                lease_expires_at=None,
                version=agent.version + 1,
            )
            if agent.reserved_call_id:
                call = await Call.filter(id=agent.reserved_call_id).using_db(conn).first()
                if call and call.state in {
                    CallState.RESERVED,
                    CallState.INITIATED,
                    CallState.RINGING,
                }:
                    # Best-effort provider reconcile outside lock would be ideal;
                    # mark failed if still transient.
                    await Call.filter(id=call.id).using_db(conn).update(
                        state=CallState.FAILED,
                        fail_reason="lease_expired",
                        ended_at=now,
                    )
            fixed += 1
        expired_jobs = await CallJob.filter(
            status="IN_PROGRESS", lease_expires_at__lt=now
        ).using_db(conn)
        for job in expired_jobs:
            await CallJob.filter(id=job.id).using_db(conn).update(
                status="PENDING", locked_by=None, lease_expires_at=None
            )
            fixed += 1

        # Stuck CONNECTED without agent heartbeat past long lease → leave alone;
        # wrap-ups completed outside.
    fixed += await complete_wrap_ups(now)
    return fixed


def main() -> None:
    from app.workers.__main__ import main as _main

    _main()


if __name__ == "__main__":
    main()
