from __future__ import annotations

import asyncio
import logging
import os
import signal

from app.db.bootstrap import close_db, init_db
from app.domain.metrics import refresh_leases
from app.domain.models import Campaign, SystemFlag
from app.settings import get_settings
from app.workers.runtime import claim_job, pacing_tick, process_job, reaper_once

log = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO)


async def run_worker() -> None:
    settings = get_settings()
    worker_id = settings.worker_id or os.getenv("HOSTNAME", "worker")
    await init_db(generate_schemas=True)
    stop = asyncio.Event()

    def _stop(*_args):  # noqa: ANN001
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    while not stop.is_set():
        flag = await SystemFlag.filter(key="kill_worker").first()
        if flag and flag.value == "1":
            await SystemFlag.filter(key="kill_worker").update(value="0")
            log.warning("chaos kill worker")
            break
        if settings.chaos_kill_worker or os.getenv("CHAOS_KILL_WORKER") == "1":
            log.warning("chaos kill worker")
            break

        try:
            await refresh_leases(worker_id)
        except Exception:  # noqa: BLE001
            log.exception("heartbeat failed")

        campaigns = await Campaign.filter(status="running")
        for c in campaigns:
            try:
                result = await pacing_tick(c.id, worker_id)
                if result:
                    log.info("pacing %s %s", c.id, result)
            except Exception:  # noqa: BLE001
                log.exception("pacing tick failed")
            for _ in range(8):
                job = await claim_job(c.id, worker_id)
                if job is None:
                    break
                try:
                    await process_job(job, worker_id)
                except Exception:  # noqa: BLE001
                    log.exception("job failed %s", job.id)
                await refresh_leases(worker_id)
        try:
            await reaper_once()
        except Exception:  # noqa: BLE001
            log.exception("reaper failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.pacing_tick_seconds)
        except asyncio.TimeoutError:
            pass
    await close_db()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
