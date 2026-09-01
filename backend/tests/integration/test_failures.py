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
async def test_lease_expiry_frees_agent(ready):
    from app.domain.models import Agent, Call, Campaign
    from app.domain.states import AgentState, CallState
    from app.workers.runtime import reaper_once

    c = await Campaign.create(id=uuid4(), name="crash", status="running")
    call_id = uuid4()
    past = datetime.now(timezone.utc) - timedelta(seconds=60)
    agent = await Agent.create(
        id=uuid4(),
        campaign_id=c.id,
        external_ref="x",
        state=AgentState.RESERVED,
        locked_by="dead-worker",
        lease_expires_at=past,
        reserved_call_id=call_id,
    )
    await Call.create(
        id=call_id,
        campaign_id=c.id,
        agent_id=agent.id,
        state=CallState.INITIATED,
        queued_at=past,
    )
    fixed = await reaper_once()
    assert fixed >= 1
    fresh = await Agent.get(id=agent.id)
    assert fresh.state == AgentState.AVAILABLE
    call = await Call.get(id=call_id)
    assert call.state == CallState.FAILED


@pytest.mark.asyncio
async def test_safety_invariant_progressive_capacity(ready):
    from app.domain.models import Agent, Campaign, PacingMetrics
    from app.domain.states import AgentState
    from app.workers.runtime import pacing_tick

    c = await Campaign.create(
        id=uuid4(),
        name="cap",
        status="running",
        pacing_mode="progressive",
        overdial_allowance=0,
        min_warmup_samples=1,
    )
    await PacingMetrics.create(campaign_id=c.id, samples=50)
    for i in range(3):
        await Agent.create(
            id=uuid4(),
            campaign_id=c.id,
            external_ref=f"a{i}",
            state=AgentState.AVAILABLE,
        )
    result = await pacing_tick(c.id, "t")
    assert result is not None
    assert result["approved"] <= 3
