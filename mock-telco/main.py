from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="mock-telco")

# Global chaos / profile state
STATE: dict[str, Any] = {
    "failing": False,
    "profile_override": None,
    "calls": {},
}


class ChaosBody(BaseModel):
    provider: str | None = None
    failing: bool = False
    profile: str | None = None


@app.get("/health")
async def health():
    return {"ok": True, "state": {k: STATE[k] for k in ("failing", "profile_override")}}


@app.post("/chaos")
async def chaos(body: ChaosBody):
    STATE["failing"] = body.failing
    if body.profile:
        STATE["profile_override"] = body.profile
    # Per-provider fail map (optional); global flag still used for simplicity
    if body.provider:
        STATE.setdefault("failing_by_provider", {})[body.provider] = body.failing
    return {
        "failing": STATE["failing"],
        "profile": STATE["profile_override"],
        "provider": body.provider,
    }


@app.post("/calls")
async def create_call(body: dict[str, Any]):
    if STATE["failing"]:
        raise HTTPException(status_code=503, detail="provider_down")
    profile = STATE["profile_override"] or body.get("profile") or "a"
    call_id = f"mt-{uuid.uuid4()}"
    STATE["calls"][call_id] = {"state": "initiated", "profile": profile}
    webhook_url = body["webhook_url"]
    metadata = body.get("metadata") or {}
    asyncio.create_task(_lifecycle(call_id, webhook_url, profile, metadata))
    return {"call_id": call_id}


@app.get("/calls/{call_id}")
async def get_call(call_id: str):
    return STATE["calls"].get(call_id, {"state": "unknown"})


@app.post("/calls/{call_id}/hangup")
async def hangup(call_id: str):
    if call_id in STATE["calls"]:
        STATE["calls"][call_id]["state"] = "cancelled"
    return {"ok": True}


@app.post("/calls/{call_id}/safe-harbour")
async def safe_harbour(call_id: str):
    meta = STATE["calls"].get(call_id, {})
    webhook = meta.get("webhook_url")
    STATE["calls"][call_id]["state"] = "completed"
    if webhook:
        await _post_event(
            webhook,
            call_id,
            "completed",
            {"safe_harbour": True},
        )
    return {"ok": True, "state": "completed"}


async def _post_event(
    webhook_url: str,
    call_id: str,
    event_type: str,
    metadata: dict,
    *,
    duplicate: bool = False,
) -> None:
    event_id = str(uuid.uuid4())
    payload = {
        "event_id": event_id,
        "call_id": call_id,
        "type": event_type,
        "metadata": metadata,
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(webhook_url, json=payload)
            if duplicate:
                await client.post(webhook_url, json=payload)
        except Exception:
            pass


async def _lifecycle(call_id: str, webhook_url: str, profile: str, metadata: dict) -> None:
    STATE["calls"][call_id]["webhook_url"] = webhook_url
    time_scale = float(metadata.get("time_scale") or 60)
    answer_rate = float(metadata.get("answer_rate") or 0.5)
    talk_sec = float(metadata.get("talk_sec") or 90)
    rng = random.Random(call_id)
    messy = profile in {"b", "mock_b"}

    delay = (0.2 if not messy else rng.uniform(0.5, 2.0)) / max(time_scale / 60, 0.1)
    await asyncio.sleep(delay)
    if STATE["failing"]:
        await _post_event(webhook_url, call_id, "failed", metadata)
        STATE["calls"][call_id]["state"] = "failed"
        return

    events = ["ringing"]
    if rng.random() < answer_rate:
        events += ["answered", "completed"]
    else:
        events += ["failed"]

    if messy and rng.random() < 0.4:
        rng.shuffle(events)

    for et in events:
        STATE["calls"][call_id]["state"] = et
        dup = messy and rng.random() < 0.3
        await _post_event(webhook_url, call_id, et, metadata, duplicate=dup)
        phase = (talk_sec if et == "answered" else 5) / max(time_scale, 1)
        await asyncio.sleep(max(0.05, phase))
