from __future__ import annotations

import math

from app.pacing.types import CampaignSnapshot, DialRequest


def progressive_desired(snap: CampaignSnapshot) -> int:
    return max(0, snap.available_agents - snap.agent_bound_inflight - snap.pending_jobs)


def _binom_tail_p_gt(n: int, p: float, threshold: int) -> float:
    """P(X > threshold) for X~Binomial(n,p) via normal approximation with continuity."""
    if n <= 0:
        return 0.0
    p = min(max(p, 1e-6), 1 - 1e-6)
    mu = n * p
    var = n * p * (1 - p)
    sigma = math.sqrt(var)
    if sigma < 1e-9:
        return 0.0 if mu <= threshold else 1.0
    z = ((threshold + 0.5) - mu) / sigma
    return 0.5 * math.erfc(z / math.sqrt(2))


def predictive_desired(snap: CampaignSnapshot) -> DialRequest:
    expected_from_ringing = int(round(snap.ringing * snap.answer_rate_ewma))
    # Agents expected free soon: wrap-ups + fraction of connected finishing within setup horizon
    setup = max(1.0, snap.setup_sec_ewma)
    talk = max(1.0, snap.talk_sec_ewma)
    frees_from_talk = int(round(snap.connected_agents * min(1.0, setup / talk)))
    projected_free = max(
        0,
        snap.available_agents + snap.wrap_up_agents + frees_from_talk - expected_from_ringing,
    )
    raw_n = 0
    tail_at_n = 0.0
    for n in range(0, max(projected_free * 4, 1) + 1):
        tail = _binom_tail_p_gt(n, snap.answer_rate_ewma, projected_free)
        if tail <= snap.target_abandon_prob:
            raw_n = n
            tail_at_n = tail
        else:
            break
    trimmed = int(raw_n * snap.aggressiveness)
    capped = min(trimmed, snap.contact_inventory, max(0, projected_free * 3))
    capped = max(0, capped - snap.pending_jobs)
    return DialRequest(
        campaign_id=snap.campaign_id,
        desired_count=capped,
        mode="predictive",
        reasoning={
            "a_hat": snap.answer_rate_ewma,
            "setup_sec_ewma": snap.setup_sec_ewma,
            "talk_sec_ewma": snap.talk_sec_ewma,
            "wrap_up_agents": snap.wrap_up_agents,
            "connected_agents": snap.connected_agents,
            "frees_from_talk": frees_from_talk,
            "projected_free": projected_free,
            "expected_from_ringing": expected_from_ringing,
            "target_p": snap.target_abandon_prob,
            "tail_at_n": tail_at_n,
            "raw_n": raw_n,
            "aggressiveness": snap.aggressiveness,
            "why": "tail_bound_trimmed",
        },
    )


def compute_dial_request(snap: CampaignSnapshot) -> DialRequest:
    mode = snap.pacing_mode
    if snap.force_progressive:
        mode = "progressive"
    warm = snap.samples < snap.min_warmup_samples
    if mode == "auto":
        mode = "progressive" if warm else "predictive"
    if mode == "progressive" or warm:
        n = progressive_desired(snap)
        return DialRequest(
            campaign_id=snap.campaign_id,
            desired_count=n,
            mode="progressive",
            reasoning={
                "available": snap.available_agents,
                "inflight": snap.agent_bound_inflight,
                "pending_jobs": snap.pending_jobs,
                "warmup": warm,
                "samples": snap.samples,
                "why": "progressive_capacity",
            },
        )
    return predictive_desired(snap)
