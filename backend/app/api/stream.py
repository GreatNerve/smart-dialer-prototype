from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.api.routes import campaign_snapshot

stream_router = APIRouter()


def _delta(prev: dict | None, curr: dict) -> dict:
    if not prev:
        return {"full": True}
    keys = ("agents", "calls", "metrics", "provider_health", "status", "force_progressive")
    changed = {k: curr.get(k) for k in keys if prev.get(k) != curr.get(k)}
    if curr.get("decisions") and (
        not prev.get("decisions")
        or prev["decisions"][0]["id"] != curr["decisions"][0]["id"]
    ):
        changed["last_decision"] = curr["decisions"][0]
        changed["pacing_timeline"] = curr.get("pacing_timeline")
    return changed


@stream_router.get("/api/stream")
async def stream(request: Request, campaign_id: UUID = Query(...)):
    async def gen():
        prev: dict | None = None
        while True:
            if await request.is_disconnected():
                break
            try:
                snap = await campaign_snapshot(campaign_id)
                if prev is None:
                    yield f"event: snapshot\ndata: {json.dumps(snap)}\n\n"
                else:
                    d = _delta(prev, snap)
                    if d:
                        # Always include identity so clients can merge
                        payload = {"campaign_id": str(campaign_id), **d, "snapshot": snap}
                        yield f"event: delta\ndata: {json.dumps(payload)}\n\n"
                prev = snap
            except Exception as exc:  # noqa: BLE001
                yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
