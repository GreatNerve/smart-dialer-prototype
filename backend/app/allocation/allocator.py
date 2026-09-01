from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from tortoise.transactions import in_transaction

from app.domain.models import Agent, Call, Campaign, CampaignContact
from app.domain.reservation import claim_contact, release_agent_to_available, reserve_agent
from app.domain.states import AgentState, CallState
from app.providers.health import record_provider_attempt
from app.providers.port import TelecomProvider
from app.safety.controller import ApprovedDialBatch
from app.settings import get_settings


class CallAllocator:
    """Accepts only ApprovedDialBatch — pacing cannot call this with a raw int."""

    def __init__(self, provider: TelecomProvider) -> None:
        self.provider = provider

    async def execute_one(
        self,
        batch: ApprovedDialBatch,
        *,
        campaign: Campaign,
        worker_id: str,
        now: datetime,
    ) -> Call | None:
        if not isinstance(batch, ApprovedDialBatch):
            raise TypeError("allocator requires ApprovedDialBatch capability token")
        settings = get_settings()
        lease = timedelta(seconds=settings.lease_ttl_seconds)
        call_id = uuid4()
        idem = f"{batch.decision_id}:{call_id}"

        contact = await claim_contact(
            campaign_id=campaign.id,
            call_id=call_id,
            now=now,
            window_start_hour=getattr(campaign, "window_start_hour", 0),
            window_end_hour=getattr(campaign, "window_end_hour", 24),
        )
        if contact is None:
            return None

        agent = await reserve_agent(
            campaign_id=campaign.id,
            worker_id=worker_id,
            call_id=call_id,
            now=now,
            lease_ttl=lease,
        )
        if agent is None and batch.mode == "progressive":
            await CampaignContact.filter(id=contact.id).update(status="eligible")
            return None

        try:
            call = await Call.create(
                id=call_id,
                campaign_id=campaign.id,
                agent_id=agent.id if agent else None,
                contact_id=contact.id,
                provider_name=self.provider.name,
                idempotency_key=idem,
                state=CallState.RESERVED if agent else CallState.QUEUED,
                decision_id=batch.decision_id,
                worker_id=worker_id,
                lease_expires_at=now + lease,
                queued_at=now,
                reserved_at=now if agent else None,
            )

            webhook = f"{settings.webhook_base_url}/webhooks/provider/{self.provider.name}"
            t0 = time.perf_counter()
            result = await self.provider.initiate_call(
                to_number=contact.phone,
                from_number="+10000000000",
                webhook_url=webhook,
                idempotency_key=idem,
                metadata={
                    "campaign_id": str(campaign.id),
                    "call_id": str(call.id),
                    "answer_rate": campaign.answer_rate_sim,
                    "talk_sec": campaign.talk_sec_sim,
                    "time_scale": campaign.time_scale,
                },
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            await record_provider_attempt(
                self.provider.name,
                success=result.accepted,
                latency_ms=latency_ms,
            )

            if not result.accepted:
                await self._fail_call(
                    call,
                    agent.id if agent else None,
                    contact.id,
                    result.error or "initiate_failed",
                )
                return call

            async with in_transaction() as conn:
                await Call.filter(id=call.id, version=call.version).using_db(conn).update(
                    state=CallState.INITIATED,
                    version=call.version + 1,
                    provider_call_id=result.provider_call_id,
                    initiated_at=now,
                )
                if agent is not None:
                    await Agent.filter(
                        id=agent.id, state=AgentState.RESERVED, version=agent.version
                    ).using_db(conn).update(
                        state=AgentState.DIALING,
                        version=agent.version + 1,
                    )
            call.state = CallState.INITIATED
            call.provider_call_id = result.provider_call_id
            return call
        except Exception:
            if agent is not None:
                await release_agent_to_available(
                    agent.id, [AgentState.RESERVED, AgentState.DIALING]
                )
            await CampaignContact.filter(id=contact.id).update(status="eligible")
            raise

    async def _fail_call(
        self,
        call: Call,
        agent_id: UUID | None,
        contact_id: UUID,
        reason: str,
    ) -> None:
        await Call.filter(id=call.id).update(
            state=CallState.FAILED,
            fail_reason=reason,
            ended_at=datetime.now(timezone.utc),
        )
        if agent_id is not None:
            await release_agent_to_available(
                agent_id, [AgentState.RESERVED, AgentState.DIALING]
            )
        await CampaignContact.filter(id=contact_id).update(status="eligible")
