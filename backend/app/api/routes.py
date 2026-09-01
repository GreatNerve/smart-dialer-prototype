from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from tortoise.functions import Count

from app.allocation.projection import ingest_provider_event
from app.domain.models import (
    Agent,
    Call,
    Campaign,
    CampaignContact,
    PacingMetrics,
    ProviderHealth,
    SafetyDecision,
)
from app.domain.states import AgentState
from app.providers.registry import get_provider
from app.settings import get_settings

router = APIRouter()


class CampaignCreate(BaseModel):
    name: str
    pacing_mode: str = "auto"
    provider_name: str = "mock_a"
    time_scale: float = 60.0
    overdial_allowance: int = 5
    answer_rate_sim: float = 0.5
    talk_sec_sim: float = 90.0
    window_start_hour: int = 0
    window_end_hour: int = 24


class CampaignPatch(BaseModel):
    pacing_mode: str | None = None
    provider_name: str | None = None
    force_progressive: bool | None = None
    overdial_allowance: int | None = None
    answer_rate_sim: float | None = None
    talk_sec_sim: float | None = None
    time_scale: float | None = None


class SeedBody(BaseModel):
    agents: int = 50
    contacts: int = 500
    answer_rate: float | None = None
    talk_sec: float | None = None


class ChaosProviderBody(BaseModel):
    provider: str = "mock_a"
    failing: bool = False
    profile: str | None = None


class DropAgentsBody(BaseModel):
    campaign_id: UUID
    count: int = 40


class ForceProgressiveBody(BaseModel):
    campaign_id: UUID
    enabled: bool = True


@router.post("/api/campaigns")
async def create_campaign(body: CampaignCreate) -> dict[str, Any]:
    c = await Campaign.create(
        id=uuid4(),
        name=body.name,
        pacing_mode=body.pacing_mode,
        provider_name=body.provider_name,
        time_scale=body.time_scale,
        overdial_allowance=body.overdial_allowance,
        answer_rate_sim=body.answer_rate_sim,
        talk_sec_sim=body.talk_sec_sim,
        window_start_hour=body.window_start_hour,
        window_end_hour=body.window_end_hour,
    )
    await PacingMetrics.create(campaign_id=c.id)
    await ProviderHealth.get_or_create(provider_name=c.provider_name)
    return {"id": str(c.id), "name": c.name}


@router.patch("/api/campaigns/{campaign_id}")
async def patch_campaign(campaign_id: UUID, body: CampaignPatch) -> dict[str, Any]:
    c = await Campaign.filter(id=campaign_id).first()
    if not c:
        raise HTTPException(404, "campaign not found")
    data = body.model_dump(exclude_none=True)
    if data:
        await Campaign.filter(id=campaign_id).update(**data)
        if "provider_name" in data:
            await ProviderHealth.get_or_create(provider_name=data["provider_name"])
    return await campaign_snapshot(campaign_id)


@router.get("/api/campaigns")
async def list_campaigns() -> list[dict[str, Any]]:
    rows = await Campaign.all().order_by("-created_at")
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "status": c.status,
            "provider_name": c.provider_name,
            "pacing_mode": c.pacing_mode,
        }
        for c in rows
    ]


@router.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: UUID) -> dict[str, Any]:
    c = await Campaign.filter(id=campaign_id).first()
    if not c:
        raise HTTPException(404, "campaign not found")
    return await campaign_snapshot(campaign_id)


@router.post("/api/campaigns/{campaign_id}/seed")
async def seed_campaign(campaign_id: UUID, body: SeedBody) -> dict[str, Any]:
    c = await Campaign.filter(id=campaign_id).first()
    if not c:
        raise HTTPException(404, "campaign not found")
    if body.answer_rate is not None:
        c.answer_rate_sim = body.answer_rate
    if body.talk_sec is not None:
        c.talk_sec_sim = body.talk_sec
    await c.save()
    for i in range(body.agents):
        await Agent.create(
            id=uuid4(),
            campaign_id=c.id,
            external_ref=f"agent-{i}",
            state=AgentState.AVAILABLE,
        )
    for i in range(body.contacts):
        await CampaignContact.create(
            id=uuid4(),
            campaign_id=c.id,
            phone=f"+1555{i:07d}",
            priority=i % 5,
            status="eligible",
        )
    return {"agents": body.agents, "contacts": body.contacts}


@router.post("/api/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: UUID) -> dict[str, str]:
    updated = await Campaign.filter(id=campaign_id).update(status="running")
    if not updated:
        raise HTTPException(404, "campaign not found")
    return {"status": "running"}


@router.post("/api/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: UUID) -> dict[str, str]:
    updated = await Campaign.filter(id=campaign_id).update(status="stopped")
    if not updated:
        raise HTTPException(404, "campaign not found")
    return {"status": "stopped"}


async def _count_by(model, campaign_id: UUID, field: str = "state") -> dict[str, int]:
    try:
        rows = (
            await model.filter(campaign_id=campaign_id)
            .annotate(n=Count("id"))
            .group_by(field)
            .values(field, "n")
        )
        return {r[field]: int(r["n"]) for r in rows}
    except Exception:  # noqa: BLE001
        items = await model.filter(campaign_id=campaign_id).only(field)
        out: dict[str, int] = {}
        for item in items:
            key = getattr(item, field)
            out[key] = out.get(key, 0) + 1
        return out


async def campaign_snapshot(campaign_id: UUID) -> dict[str, Any]:
    c = await Campaign.filter(id=campaign_id).first()
    if not c:
        raise HTTPException(404, "campaign not found")
    agent_counts = await _count_by(Agent, campaign_id)
    call_counts = await _count_by(Call, campaign_id)
    metrics = await PacingMetrics.filter(campaign_id=campaign_id).first()
    decisions = (
        await SafetyDecision.filter(campaign_id=campaign_id)
        .order_by("-created_at")
        .limit(40)
    )
    health = await ProviderHealth.filter(provider_name=c.provider_name).first()
    answered = metrics.answered_window if metrics else 0
    abandons = metrics.abandons_window if metrics else 0
    abandon_rate = (abandons / answered) if answered else 0.0
    return {
        "id": str(c.id),
        "name": c.name,
        "status": c.status,
        "pacing_mode": c.pacing_mode,
        "force_progressive": c.force_progressive,
        "provider_name": c.provider_name,
        "time_scale": c.time_scale,
        "overdial_allowance": c.overdial_allowance,
        "abandon_rate_ceiling": c.abandon_rate_ceiling,
        "window_start_hour": c.window_start_hour,
        "window_end_hour": c.window_end_hour,
        "agents": agent_counts,
        "calls": call_counts,
        "metrics": {
            "answer_rate_ewma": metrics.answer_rate_ewma if metrics else 0,
            "setup_sec_ewma": metrics.setup_sec_ewma if metrics else 0,
            "talk_sec_ewma": metrics.talk_sec_ewma if metrics else 0,
            "samples": metrics.samples if metrics else 0,
            "aggressiveness": metrics.aggressiveness if metrics else 1,
            "abandons_window": abandons,
            "answered_window": answered,
            "abandon_rate": abandon_rate,
            "last_approved": metrics.last_approved if metrics else 0,
        },
        "pacing_timeline": [
            {
                "id": str(d.id),
                "desired": d.desired_count,
                "approved": d.approved_count,
                "outcome": d.outcome,
                "mode": d.mode,
                "reason_codes": d.reason_codes,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in reversed(list(decisions))
        ],
        "decisions": [
            {
                "id": str(d.id),
                "desired": d.desired_count,
                "approved": d.approved_count,
                "outcome": d.outcome,
                "mode": d.mode,
                "reason_codes": d.reason_codes,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in decisions
        ],
        "provider_health": {
            "provider_name": c.provider_name,
            "error_rate_ewma": health.error_rate_ewma if health else 0,
            "p95_latency_ms": health.p95_latency_ms if health else 0,
            "circuit_open_until": health.circuit_open_until.isoformat()
            if health and health.circuit_open_until
            else None,
            "circuit_open": bool(
                health
                and health.circuit_open_until
                and health.circuit_open_until.timestamp() > __import__("time").time()
            ),
        },
    }


@router.get("/api/campaigns/{campaign_id}/snapshot")
async def snapshot(campaign_id: UUID) -> dict[str, Any]:
    return await campaign_snapshot(campaign_id)


@router.get("/api/campaigns/{campaign_id}/decisions")
async def decisions(campaign_id: UUID) -> list[dict[str, Any]]:
    rows = (
        await SafetyDecision.filter(campaign_id=campaign_id)
        .order_by("-created_at")
        .limit(50)
    )
    return [
        {
            "id": str(d.id),
            "desired": d.desired_count,
            "approved": d.approved_count,
            "outcome": d.outcome,
            "codes": d.reason_codes,
        }
        for d in rows
    ]


@router.get("/api/campaigns/{campaign_id}/calls")
async def list_calls(campaign_id: UUID) -> list[dict[str, Any]]:
    rows = await Call.filter(campaign_id=campaign_id).order_by("-queued_at").limit(100)
    return [
        {"id": str(c.id), "state": c.state, "provider_call_id": c.provider_call_id}
        for c in rows
    ]


@router.post("/webhooks/provider/{provider_name}")
async def webhook(provider_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    telecom = get_provider(provider_name)
    return await ingest_provider_event(
        provider=provider_name, payload=payload, telecom=telecom
    )


@router.post("/api/chaos/kill-worker")
async def chaos_kill_worker() -> dict[str, str]:
    from app.domain.models import SystemFlag

    await SystemFlag.update_or_create(key="kill_worker", defaults={"value": "1"})
    return {"status": "kill_flag_set"}


@router.post("/api/chaos/provider")
async def chaos_provider(body: ChaosProviderBody) -> dict[str, Any]:
    import httpx

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{settings.mock_telco_url}/chaos",
            json={
                "provider": body.provider,
                "failing": body.failing,
                "profile": body.profile,
            },
        )
        return r.json()


@router.post("/api/chaos/drop-agents")
async def chaos_drop_agents(body: DropAgentsBody) -> dict[str, Any]:
    agents = await Agent.filter(
        campaign_id=body.campaign_id, state=AgentState.AVAILABLE
    ).limit(body.count)
    ids = [a.id for a in agents]
    if ids:
        await Agent.filter(id__in=ids).update(state=AgentState.OFFLINE)
    return {"dropped": len(ids)}


@router.post("/api/chaos/force-progressive")
async def chaos_force_progressive(body: ForceProgressiveBody) -> dict[str, Any]:
    await Campaign.filter(id=body.campaign_id).update(
        force_progressive=body.enabled
    )
    return {"force_progressive": body.enabled}
