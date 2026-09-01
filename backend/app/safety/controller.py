from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from app.pacing.types import DialRequest


@dataclass(frozen=True)
class ApprovedDialBatch:
    """Capability token — only SafetyController / this module may construct this."""

    decision_id: UUID
    campaign_id: UUID
    approved_count: int
    mode: str
    outcome: Literal["APPROVE", "REDUCE", "REJECT", "FALLBACK_PROGRESSIVE"]
    reason_codes: tuple[str, ...]
    inputs: dict[str, Any]

    @classmethod
    def from_persisted(
        cls,
        *,
        decision_id: UUID,
        campaign_id: UUID,
        mode: str,
        outcome: str,
        reason_codes: list[str] | tuple[str, ...],
        inputs: dict[str, Any],
        slot_count: int = 1,
    ) -> ApprovedDialBatch:
        """Rehydrate one job slot from a SafetyDecision row (still gated in safety package)."""
        return cls(
            decision_id=decision_id,
            campaign_id=campaign_id,
            approved_count=slot_count,
            mode=mode,
            outcome=outcome,  # type: ignore[arg-type]
            reason_codes=tuple(reason_codes),
            inputs=inputs,
        )


@dataclass
class SafetySnapshot:
    available_agents: int
    agent_bound_inflight: int
    pending_jobs: int
    overdial_allowance: int
    abandon_rate_ceiling: float
    abandons_window: int
    answered_window: int
    max_cps: float
    slew_factor: float
    last_approved: int
    force_progressive: bool
    provider_circuit_open: bool
    now: datetime
    tick_seconds: float = 1.0


class SafetyController:
    def evaluate(self, request: DialRequest, snap: SafetySnapshot) -> ApprovedDialBatch:
        codes: list[str] = []
        mode = request.mode
        approved = request.desired_count

        if snap.force_progressive or request.mode == "predictive" and snap.force_progressive:
            codes.append("FORCE_PROGRESSIVE")
            mode = "progressive"
            approved = max(0, snap.available_agents - snap.agent_bound_inflight - snap.pending_jobs)
            outcome_pref: Literal["APPROVE", "REDUCE", "REJECT", "FALLBACK_PROGRESSIVE"] = (
                "FALLBACK_PROGRESSIVE"
            )
        else:
            outcome_pref = "APPROVE"

        if snap.provider_circuit_open:
            codes.append("PROVIDER_CIRCUIT_OPEN")
            approved = 0

        allowance = 0 if mode == "progressive" else snap.overdial_allowance
        max_new = max(
            0,
            snap.available_agents + allowance - snap.agent_bound_inflight - snap.pending_jobs,
        )
        if approved > max_new:
            codes.append("CAPACITY_CLAMP")
            approved = max_new

        # Abandonment projection: assume each new dial answers with rough 0.3 if unknown
        if approved > 0 and snap.answered_window + approved > 0:
            # Conservative: assume all approved could abandon if no agents — use ceiling check
            projected_abandons = snap.abandons_window
            projected_answered = snap.answered_window + max(1, int(approved * 0.3))
            # If already near ceiling, shrink
            current_rate = snap.abandons_window / max(1, snap.answered_window)
            if current_rate >= snap.abandon_rate_ceiling * 0.9:
                codes.append("ABANDON_CEILING")
                approved = min(approved, max_new if mode == "progressive" else max(0, approved // 2))
                if mode == "predictive":
                    # Fall back toward progressive capacity
                    prog = max(
                        0,
                        snap.available_agents - snap.agent_bound_inflight - snap.pending_jobs,
                    )
                    if approved > prog:
                        approved = prog
                        codes.append("FALLBACK_PROGRESSIVE")
                        mode = "progressive"
                        outcome_pref = "FALLBACK_PROGRESSIVE"

        cps_cap = max(0, int(snap.max_cps * snap.tick_seconds))
        if approved > cps_cap:
            codes.append("CPS_CLAMP")
            approved = cps_cap

        slew_cap = max(2, int(snap.last_approved * (1 + snap.slew_factor)) + 2)
        if approved > slew_cap:
            codes.append("SLEW_CLAMP")
            approved = slew_cap

        if approved <= 0:
            outcome: Literal["APPROVE", "REDUCE", "REJECT", "FALLBACK_PROGRESSIVE"] = (
                "REJECT" if outcome_pref != "FALLBACK_PROGRESSIVE" else "FALLBACK_PROGRESSIVE"
            )
            approved = 0
        elif approved < request.desired_count:
            outcome = (
                "FALLBACK_PROGRESSIVE"
                if "FALLBACK_PROGRESSIVE" in codes or outcome_pref == "FALLBACK_PROGRESSIVE"
                else "REDUCE"
            )
        else:
            outcome = outcome_pref if outcome_pref == "FALLBACK_PROGRESSIVE" else "APPROVE"

        return ApprovedDialBatch(
            decision_id=uuid4(),
            campaign_id=request.campaign_id,
            approved_count=approved,
            mode=mode,
            outcome=outcome,
            reason_codes=tuple(codes) if codes else ("OK",),
            inputs={
                "desired": request.desired_count,
                "request_mode": request.mode,
                "reasoning": request.reasoning,
                "available": snap.available_agents,
                "inflight": snap.agent_bound_inflight,
                "pending_jobs": snap.pending_jobs,
            },
        )
