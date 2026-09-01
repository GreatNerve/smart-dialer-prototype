from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain.metrics import ewma
from app.domain.reservation import _in_calling_window
from app.domain.state_machine import (
    IllegalTransition,
    assert_agent_transition,
    assert_call_transition,
    can_project,
)
from app.domain.states import AgentState, CallState
from app.pacing.engine import compute_dial_request, progressive_desired, predictive_desired
from app.pacing.types import CampaignSnapshot
from app.providers.health import ERROR_OPEN_THRESHOLD
from app.safety.controller import ApprovedDialBatch, SafetyController, SafetySnapshot


def _snap(**kwargs) -> CampaignSnapshot:
    base = dict(
        campaign_id=uuid4(),
        available_agents=40,
        agent_bound_inflight=0,
        pending_jobs=0,
        ringing=0,
        answer_rate_ewma=0.5,
        setup_sec_ewma=15,
        talk_sec_ewma=90,
        samples=100,
        aggressiveness=1.0,
        min_warmup_samples=30,
        target_abandon_prob=0.03,
        pacing_mode="auto",
        force_progressive=False,
        contact_inventory=1000,
        abandons_window=0,
        answered_window=0,
        wrap_up_agents=0,
        connected_agents=0,
    )
    base.update(kwargs)
    return CampaignSnapshot(**base)


def test_agent_legal_and_illegal():
    assert_agent_transition(AgentState.AVAILABLE, AgentState.RESERVED)
    with pytest.raises(IllegalTransition):
        assert_agent_transition(AgentState.AVAILABLE, AgentState.CONNECTED)


def test_call_terminals_absorb():
    assert not can_project(CallState.COMPLETED, CallState.RINGING)
    assert can_project(CallState.RINGING, CallState.ANSWERED)


def test_progressive_desired():
    snap = _snap(available_agents=50, agent_bound_inflight=10, pending_jobs=5, samples=0)
    assert progressive_desired(snap) == 35
    req = compute_dial_request(snap)
    assert req.mode == "progressive"


def test_warmup_forces_progressive():
    req = compute_dial_request(_snap(samples=5, pacing_mode="auto"))
    assert req.mode == "progressive"


def test_predictive_uses_wrap_and_talk():
    req = predictive_desired(
        _snap(
            available_agents=20,
            wrap_up_agents=5,
            connected_agents=10,
            ringing=4,
            answer_rate_ewma=0.4,
            setup_sec_ewma=10,
            talk_sec_ewma=100,
        )
    )
    assert req.mode == "predictive"
    assert "projected_free" in req.reasoning
    assert req.reasoning["wrap_up_agents"] == 5
    assert req.desired_count >= 0


def test_safety_capacity_and_token():
    from app.pacing.types import DialRequest

    req = DialRequest(campaign_id=uuid4(), desired_count=20, mode="predictive", reasoning={})
    snap = SafetySnapshot(
        available_agents=5,
        agent_bound_inflight=0,
        pending_jobs=0,
        overdial_allowance=0,
        abandon_rate_ceiling=0.03,
        abandons_window=0,
        answered_window=10,
        max_cps=100,
        slew_factor=1.0,
        last_approved=20,
        force_progressive=False,
        provider_circuit_open=False,
        now=datetime.now(timezone.utc),
    )
    batch = SafetyController().evaluate(req, snap)
    assert isinstance(batch, ApprovedDialBatch)
    assert batch.approved_count <= 5
    assert "CAPACITY_CLAMP" in batch.reason_codes


def test_safety_circuit_reject():
    from app.pacing.types import DialRequest

    req = DialRequest(campaign_id=uuid4(), desired_count=10, mode="progressive", reasoning={})
    snap = SafetySnapshot(
        available_agents=10,
        agent_bound_inflight=0,
        pending_jobs=0,
        overdial_allowance=0,
        abandon_rate_ceiling=0.03,
        abandons_window=0,
        answered_window=0,
        max_cps=100,
        slew_factor=1.0,
        last_approved=0,
        force_progressive=False,
        provider_circuit_open=True,
        now=datetime.now(timezone.utc),
    )
    batch = SafetyController().evaluate(req, snap)
    assert batch.approved_count == 0
    assert "PROVIDER_CIRCUIT_OPEN" in batch.reason_codes


def test_batch_from_persisted_stays_in_safety_package():
    batch = ApprovedDialBatch.from_persisted(
        decision_id=uuid4(),
        campaign_id=uuid4(),
        mode="progressive",
        outcome="APPROVE",
        reason_codes=["OK"],
        inputs={},
    )
    assert batch.approved_count == 1


def test_calling_window():
    assert _in_calling_window(datetime(2026, 1, 1, 10, tzinfo=timezone.utc), 9, 17)
    assert not _in_calling_window(datetime(2026, 1, 1, 8, tzinfo=timezone.utc), 9, 17)
    assert _in_calling_window(datetime(2026, 1, 1, 22, tzinfo=timezone.utc), 20, 6)


def test_ewma():
    assert ewma(0.5, 1.0, 0.2) == pytest.approx(0.6)


def test_error_threshold_constant():
    assert ERROR_OPEN_THRESHOLD > 0


def test_pacing_cannot_import_providers():
    import ast
    from pathlib import Path

    pacing_root = Path(__file__).resolve().parents[2] / "app" / "pacing"
    forbidden = ("app.providers", "app.allocation")
    for path in pacing_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for f in forbidden:
                        assert not alias.name.startswith(f), path
            if isinstance(node, ast.ImportFrom) and node.module:
                for f in forbidden:
                    assert not node.module.startswith(f), path


def test_reservation_source_uses_using_db():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "app" / "domain" / "reservation.py").read_text(
        encoding="utf-8"
    )
    assert "using_db(conn)" in src
    assert "select_for_update" in src


def test_assert_call_transition_legal():
    assert_call_transition(CallState.RINGING, CallState.ANSWERED)
