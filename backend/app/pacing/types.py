from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID


@dataclass(frozen=True)
class DialRequest:
    campaign_id: UUID
    desired_count: int
    mode: Literal["progressive", "predictive"]
    reasoning: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CampaignSnapshot:
    campaign_id: UUID
    available_agents: int
    agent_bound_inflight: int
    pending_jobs: int
    ringing: int
    answer_rate_ewma: float
    setup_sec_ewma: float
    talk_sec_ewma: float
    samples: int
    aggressiveness: float
    min_warmup_samples: int
    target_abandon_prob: float
    pacing_mode: str
    force_progressive: bool
    contact_inventory: int
    abandons_window: int
    answered_window: int
    wrap_up_agents: int = 0
    connected_agents: int = 0
