from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from tortoise.transactions import in_transaction

from app.domain.models import Agent, CampaignContact
from app.domain.states import AgentState


class ReservationLost(Exception):
    pass


def _in_calling_window(now: datetime, start_hour: int, end_hour: int) -> bool:
    """Local-UTC hour window [start, end). end <= start means overnight wrap."""
    hour = now.hour
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


async def reserve_agent(
    *,
    campaign_id: UUID,
    worker_id: str,
    call_id: UUID,
    now: datetime,
    lease_ttl: timedelta,
) -> Agent | None:
    """Atomically reserve one AVAILABLE agent. Always uses using_db(conn)."""
    async with in_transaction() as conn:
        agent = (
            await Agent.filter(campaign_id=campaign_id, state=AgentState.AVAILABLE)
            .select_for_update(skip_locked=True)
            .using_db(conn)
            .order_by("id")
            .first()
        )
        if agent is None:
            return None
        rows = await Agent.filter(
            id=agent.id,
            state=AgentState.AVAILABLE,
            version=agent.version,
        ).using_db(conn).update(
            state=AgentState.RESERVED,
            version=agent.version + 1,
            locked_by=worker_id,
            lease_expires_at=now + lease_ttl,
            reserved_call_id=call_id,
        )
        if rows != 1:
            raise ReservationLost("agent CAS failed")
        agent.state = AgentState.RESERVED
        agent.version += 1
        agent.locked_by = worker_id
        agent.lease_expires_at = now + lease_ttl
        agent.reserved_call_id = call_id
        return agent


async def claim_contact(
    *,
    campaign_id: UUID,
    call_id: UUID,
    now: datetime,
    window_start_hour: int = 0,
    window_end_hour: int = 24,
) -> CampaignContact | None:
    if not _in_calling_window(now, window_start_hour, window_end_hour):
        return None

    async with in_transaction() as conn:
        contact = (
            await CampaignContact.filter(
                campaign_id=campaign_id,
                status="eligible",
                dnc=False,
                next_eligible_at__lte=now,
            )
            .select_for_update(skip_locked=True)
            .using_db(conn)
            .order_by("-priority", "next_eligible_at", "id")
            .first()
        )
        if contact is None:
            return None
        if contact.attempts >= contact.max_attempts:
            await CampaignContact.filter(id=contact.id).using_db(conn).update(
                status="exhausted"
            )
            return None
        rows = await CampaignContact.filter(
            id=contact.id,
            status="eligible",
            version=contact.version,
        ).using_db(conn).update(
            status="in_progress",
            version=contact.version + 1,
            last_call_id=call_id,
            attempts=contact.attempts + 1,
        )
        if rows != 1:
            raise ReservationLost("contact CAS failed")
        contact.status = "in_progress"
        contact.version += 1
        contact.last_call_id = call_id
        contact.attempts += 1
        return contact


async def release_agent_to_available(agent_id: UUID, expected_states: list[str]) -> bool:
    async with in_transaction() as conn:
        agent = (
            await Agent.filter(id=agent_id, state__in=expected_states)
            .select_for_update(skip_locked=True)
            .using_db(conn)
            .first()
        )
        if agent is None:
            return False
        await Agent.filter(id=agent.id, version=agent.version).using_db(conn).update(
            state=AgentState.AVAILABLE,
            version=agent.version + 1,
            locked_by=None,
            lease_expires_at=None,
            reserved_call_id=None,
        )
        return True
