from __future__ import annotations

import argparse
import asyncio
import time
from uuid import uuid4

from app.db.bootstrap import close_db, init_db
from app.domain.models import Agent, Call, Campaign, CampaignContact, PacingMetrics
from app.domain.states import AgentState
from app.workers.runtime import claim_job, pacing_tick, process_job, reaper_once

SCENARIOS = {
    "A": {"answer_rate": 0.20, "talk_sec": 120},
    "B": {"answer_rate": 0.50, "talk_sec": 90},
    "C": {"answer_rate": 0.70, "talk_sec": 180},
    "D": {"answer_rate": 0.70, "talk_sec": 90, "flip_to": 0.10},
}


async def run_sim(scenario: str, agents: int = 40, contacts: int = 400, seconds: float = 20) -> None:
    params = SCENARIOS[scenario]
    await init_db(generate_schemas=True)
    c = await Campaign.create(
        id=uuid4(),
        name=f"sim-{scenario}",
        pacing_mode="auto",
        provider_name="mock_a",
        time_scale=120,
        overdial_allowance=8,
        min_warmup_samples=5,
        answer_rate_sim=params["answer_rate"],
        talk_sec_sim=params["talk_sec"],
        status="running",
    )
    await PacingMetrics.create(
        campaign_id=c.id,
        answer_rate_ewma=params["answer_rate"],
        samples=params.get("warmup_samples", 40),
    )
    for i in range(agents):
        await Agent.create(
            id=uuid4(),
            campaign_id=c.id,
            external_ref=f"a-{i}",
            state=AgentState.AVAILABLE,
        )
    for i in range(contacts):
        await CampaignContact.create(
            id=uuid4(),
            campaign_id=c.id,
            phone=f"+1666{i:07d}",
            status="eligible",
        )

    worker_id = "sim-worker"
    start = time.time()
    flipped = False
    while time.time() - start < seconds:
        if scenario == "D" and not flipped and time.time() - start > seconds / 2:
            c.answer_rate_sim = params["flip_to"]
            await c.save()
            flipped = True
            print("flipped answer rate to", params["flip_to"])
        await pacing_tick(c.id, worker_id)
        for _ in range(10):
            job = await claim_job(c.id, worker_id)
            if not job:
                break
            try:
                await process_job(job, worker_id)
            except Exception as exc:  # noqa: BLE001
                print("job err", exc)
        await reaper_once()
        await asyncio.sleep(0.5)

    calls = await Call.filter(campaign_id=c.id)
    by = {}
    for call in calls:
        by[call.state] = by.get(call.state, 0) + 1
    print("scenario", scenario, "calls", by)
    await close_db()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="B", choices=list(SCENARIOS))
    p.add_argument("--seconds", type=float, default=15)
    args = p.parse_args()
    asyncio.run(run_sim(args.scenario, seconds=args.seconds))


if __name__ == "__main__":
    main()
