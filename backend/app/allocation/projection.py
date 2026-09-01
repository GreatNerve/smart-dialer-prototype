from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.domain.metrics import ewma, roll_metrics_window
from app.domain.models import Agent, Call, CampaignContact, PacingMetrics, ProviderEvent
from app.domain.state_machine import can_project
from app.domain.states import (
    EVENT_TO_CALL_STATE,
    AgentState,
    CallState,
)
from app.providers.port import TelecomProvider


async def ingest_provider_event(
    *,
    provider: str,
    payload: dict[str, Any],
    telecom: TelecomProvider | None = None,
) -> dict[str, Any]:
    event_id = str(payload.get("event_id") or uuid4())
    provider_call_id = str(payload.get("call_id") or "")
    event_type = str(payload.get("type") or "")
    try:
        await ProviderEvent.create(
            id=uuid4(),
            provider=provider,
            provider_event_id=event_id,
            provider_call_id=provider_call_id,
            event_type=event_type,
            payload=payload,
            out_of_order=False,
        )
    except IntegrityError:
        return {"status": "duplicate"}

    call = await Call.filter(provider_call_id=provider_call_id).first()
    if call is None and payload.get("metadata", {}).get("call_id"):
        call = await Call.filter(id=payload["metadata"]["call_id"]).first()
    if call is None:
        return {"status": "ignored_unknown_call"}

    proposed = EVENT_TO_CALL_STATE.get(event_type)
    if proposed is None:
        return {"status": "ignored_unknown_type"}

    now = datetime.now(timezone.utc)
    out_of_order = not can_project(call.state, proposed)

    if out_of_order:
        await ProviderEvent.filter(provider=provider, provider_event_id=event_id).update(
            out_of_order=True
        )
        await _backfill_timestamps(call, proposed, now)
        return {"status": "out_of_order", "state": call.state}

    async with in_transaction() as conn:
        fresh = (
            await Call.filter(id=call.id)
            .select_for_update()
            .using_db(conn)
            .first()
        )
        if fresh is None or not can_project(fresh.state, proposed):
            return {"status": "race_skip"}

        updates: dict[str, Any] = {
            "state": proposed,
            "version": fresh.version + 1,
        }
        if proposed == CallState.RINGING:
            updates["ringing_at"] = now
        elif proposed == CallState.ANSWERED:
            updates["answered_at"] = now
        elif proposed == CallState.CONNECTED:
            updates["connected_at"] = now
        elif proposed in {
            CallState.COMPLETED,
            CallState.FAILED,
            CallState.CANCELLED,
            CallState.ABANDONED,
        }:
            updates["ended_at"] = now

        rows = await Call.filter(id=fresh.id, version=fresh.version).using_db(conn).update(
            **updates
        )
        if rows != 1:
            return {"status": "cas_conflict"}
        old_state = CallState(fresh.state)

    # Reload for transition side-effects
    call = await Call.get(id=call.id)
    await _on_transition(call, old_state, proposed, telecom)
    return {"status": "applied", "state": proposed}


async def _backfill_timestamps(call: Call, proposed: CallState, now: datetime) -> None:
    if proposed == CallState.RINGING and call.ringing_at is None:
        await Call.filter(id=call.id).update(ringing_at=now)
    if proposed == CallState.ANSWERED and call.answered_at is None:
        await Call.filter(id=call.id).update(answered_at=now)


async def _on_transition(
    call: Call,
    old: CallState,
    new: CallState,
    telecom: TelecomProvider | None,
) -> None:
    metrics, _ = await PacingMetrics.get_or_create(campaign_id=call.campaign_id)
    await roll_metrics_window(metrics)
    now = datetime.now(timezone.utc)

    if new == CallState.RINGING and call.initiated_at:
        setup = max(0.0, (now - call.initiated_at).total_seconds())
        metrics.setup_sec_ewma = ewma(metrics.setup_sec_ewma, setup)
        await metrics.save()

    if new == CallState.ANSWERED:
        agent = await Agent.filter(id=call.agent_id).first() if call.agent_id else None
        if agent is None:
            from app.domain.reservation import reserve_agent
            from app.settings import get_settings

            settings = get_settings()
            agent = await reserve_agent(
                campaign_id=call.campaign_id,
                worker_id=call.worker_id or "bridge",
                call_id=call.id,
                now=now,
                lease_ttl=timedelta(seconds=settings.lease_ttl_seconds),
            )
            if agent:
                await Call.filter(id=call.id).update(agent_id=agent.id)

        if agent and agent.state in {
            AgentState.RESERVED,
            AgentState.DIALING,
            AgentState.AVAILABLE,
        }:
            await Call.filter(id=call.id, state=CallState.ANSWERED).update(
                state=CallState.CONNECTED, connected_at=now
            )
            await Agent.filter(id=agent.id).update(state=AgentState.CONNECTED)
            metrics.answered_window += 1
            metrics.samples += 1
            metrics.answer_rate_ewma = ewma(metrics.answer_rate_ewma, 1.0)
            await metrics.save()
            return

        if telecom and call.provider_call_id:
            await telecom.play_safe_harbour(call.provider_call_id)
        await Call.filter(id=call.id).update(state=CallState.ABANDONED, ended_at=now)
        metrics.abandons_window += 1
        metrics.answered_window += 1
        metrics.aggressiveness = max(0.2, metrics.aggressiveness * 0.5)
        await metrics.save()
        return

    if new == CallState.FAILED:
        metrics.answer_rate_ewma = ewma(metrics.answer_rate_ewma, 0.0)
        metrics.samples += 1
        await metrics.save()
        if call.agent_id:
            await Agent.filter(id=call.agent_id).update(
                state=AgentState.AVAILABLE, locked_by=None, lease_expires_at=None
            )
        if call.contact_id:
            contact = await CampaignContact.filter(id=call.contact_id).first()
            if contact:
                backoff = min(300, 2 ** max(1, contact.attempts))
                await CampaignContact.filter(id=contact.id).update(
                    status="eligible"
                    if contact.attempts < contact.max_attempts
                    else "exhausted",
                    next_eligible_at=now + timedelta(seconds=backoff),
                )

    if new == CallState.COMPLETED:
        if call.connected_at:
            talk = max(0.0, (now - call.connected_at).total_seconds())
            metrics.talk_sec_ewma = ewma(metrics.talk_sec_ewma, talk)
        if call.agent_id:
            # Stay in WRAP_UP until complete_wrap_ups promotes to AVAILABLE
            await Agent.filter(id=call.agent_id).update(
                state=AgentState.WRAP_UP,
                locked_by=None,
                lease_expires_at=None,
            )
        if call.contact_id:
            await CampaignContact.filter(id=call.contact_id).update(status="done")
        metrics.samples += 1
        # Quiet completion nudges aggressiveness up slightly
        if metrics.abandons_window == 0:
            metrics.aggressiveness = min(1.0, metrics.aggressiveness + 0.02)
        await metrics.save()
