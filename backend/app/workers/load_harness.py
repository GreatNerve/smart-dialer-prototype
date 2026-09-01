from __future__ import annotations

import argparse
import asyncio
import time
from uuid import uuid4

from app.db.bootstrap import close_db, init_db
from app.domain.models import Agent, Campaign, CampaignContact, PacingMetrics
from app.domain.reservation import reserve_agent
from app.domain.states import AgentState
from app.workers.runtime import build_snapshot, pacing_tick


async def run_load(agents: int) -> None:
    await init_db(generate_schemas=True)
    c = await Campaign.create(
        id=uuid4(),
        name=f"load-{agents}",
        pacing_mode="progressive",
        status="running",
        time_scale=120,
        min_warmup_samples=1,
    )
    await PacingMetrics.create(campaign_id=c.id, samples=100)
    for i in range(agents):
        await Agent.create(
            id=uuid4(),
            campaign_id=c.id,
            external_ref=f"L-{i}",
            state=AgentState.AVAILABLE,
        )
    for i in range(agents * 5):
        await CampaignContact.create(
            id=uuid4(),
            campaign_id=c.id,
            phone=f"+1777{i:07d}",
            status="eligible",
        )

    t0 = time.perf_counter()
    result = await pacing_tick(c.id, "load-worker")
    tick_ms = (time.perf_counter() - t0) * 1000

    # Reservation throughput sample
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    t1 = time.perf_counter()
    reserved = 0
    for _ in range(min(200, agents)):
        a = await reserve_agent(
            campaign_id=c.id,
            worker_id="bench",
            call_id=uuid4(),
            now=now,
            lease_ttl=timedelta(seconds=30),
        )
        if a:
            reserved += 1
    reserve_s = reserved / max(time.perf_counter() - t1, 1e-6)

    snap = await build_snapshot(c)
    print(
        {
            "agents": agents,
            "tick_ms": round(tick_ms, 2),
            "reserve_per_s": round(reserve_s, 2),
            "pacing_result": result,
            "available_after": snap.available_agents,
        }
    )
    await close_db()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agents", type=int, default=100)
    args = p.parse_args()
    asyncio.run(run_load(args.agents))


if __name__ == "__main__":
    main()
