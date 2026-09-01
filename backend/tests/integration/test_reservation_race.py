from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL") and not os.getenv("RUN_PG_TESTS"),
    reason="Set DATABASE_URL or RUN_PG_TESTS=1 for Postgres integration tests",
)


@pytest.fixture
async def db():
    os.environ.setdefault("DATABASE_URL", "postgres://dialer:dialer@localhost:5432/dialer")
    from app.db.bootstrap import close_db, init_db
    from app.domain.models import Agent, Campaign
    from app.domain.states import AgentState

    await init_db(generate_schemas=True)
    c = await Campaign.create(id=uuid4(), name="race", status="idle")
    await Agent.create(
        id=uuid4(),
        campaign_id=c.id,
        external_ref="only",
        state=AgentState.AVAILABLE,
    )
    yield c
    await close_db()


@pytest.mark.asyncio
async def test_parallel_reserve_one_winner(db):
    from app.domain.models import Agent
    from app.domain.reservation import reserve_agent
    from app.domain.states import AgentState

    campaign = db
    now = datetime.now(timezone.utc)

    async def attempt(i: int):
        try:
            return await reserve_agent(
                campaign_id=campaign.id,
                worker_id=f"w{i}",
                call_id=uuid4(),
                now=now,
                lease_ttl=timedelta(seconds=30),
            )
        except Exception:
            return None

    results = await asyncio.gather(*[attempt(i) for i in range(20)])
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    reserved = await Agent.filter(campaign_id=campaign.id, state=AgentState.RESERVED).count()
    assert reserved == 1
