from __future__ import annotations

import os
from datetime import datetime, timezone
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
async def test_duplicate_and_out_of_order_events(ready):
    from app.allocation.projection import ingest_provider_event
    from app.domain.models import Call, Campaign
    from app.domain.states import CallState

    c = await Campaign.create(id=uuid4(), name="evt", status="idle")
    call = await Call.create(
        id=uuid4(),
        campaign_id=c.id,
        provider_name="mock_a",
        provider_call_id="pc-1",
        state=CallState.INITIATED,
        queued_at=datetime.now(timezone.utc),
    )
    payload = {"event_id": "e1", "call_id": "pc-1", "type": "completed"}
    r1 = await ingest_provider_event(provider="mock_a", payload=payload)
    r2 = await ingest_provider_event(provider="mock_a", payload=payload)
    assert r1["status"] == "applied"
    assert r2["status"] == "duplicate"
    await ingest_provider_event(
        provider="mock_a",
        payload={"event_id": "e2", "call_id": "pc-1", "type": "ringing"},
    )
    fresh = await Call.get(id=call.id)
    assert fresh.state == CallState.COMPLETED
