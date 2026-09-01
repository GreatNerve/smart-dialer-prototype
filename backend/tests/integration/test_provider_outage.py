from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") and not os.getenv("RUN_PG_TESTS"),
    reason="Postgres required",
)


@pytest.fixture
async def ready():
    os.environ.setdefault("DATABASE_URL", "postgres://dialer:dialer@localhost:5432/dialer")
    from app.db.bootstrap import close_db, init_db

    await init_db(generate_schemas=True)
    yield
    await close_db()


@pytest.mark.asyncio
async def test_provider_health_opens_circuit(ready):
    from app.providers.health import is_circuit_open, record_provider_attempt

    name = f"test-{uuid4().hex[:8]}"
    for _ in range(8):
        await record_provider_attempt(name, success=False, latency_ms=100)
    assert await is_circuit_open(name)


@pytest.mark.asyncio
async def test_agent_drop_reduces_available(ready):
    from app.domain.models import Agent, Campaign
    from app.domain.states import AgentState

    c = await Campaign.create(id=uuid4(), name="drop", status="idle")
    for i in range(10):
        await Agent.create(
            id=uuid4(),
            campaign_id=c.id,
            external_ref=f"a{i}",
            state=AgentState.AVAILABLE,
        )
    agents = await Agent.filter(campaign_id=c.id, state=AgentState.AVAILABLE).limit(4)
    await Agent.filter(id__in=[a.id for a in agents]).update(state=AgentState.OFFLINE)
    left = await Agent.filter(campaign_id=c.id, state=AgentState.AVAILABLE).count()
    assert left == 6


@pytest.mark.asyncio
async def test_contact_backoff_applied(ready):
    from app.allocation.projection import _on_transition
    from app.domain.models import Call, Campaign, CampaignContact
    from app.domain.states import CallState

    c = await Campaign.create(id=uuid4(), name="bo", status="idle")
    contact = await CampaignContact.create(
        id=uuid4(),
        campaign_id=c.id,
        phone="+100",
        attempts=2,
        max_attempts=3,
        status="in_progress",
    )
    call = await Call.create(
        id=uuid4(),
        campaign_id=c.id,
        contact_id=contact.id,
        state=CallState.FAILED,
        queued_at=datetime.now(timezone.utc),
    )
    await _on_transition(call, CallState.RINGING, CallState.FAILED, None)
    fresh = await CampaignContact.get(id=contact.id)
    assert fresh.next_eligible_at > datetime.now(timezone.utc) - timedelta(seconds=1)
    assert fresh.status == "eligible"
