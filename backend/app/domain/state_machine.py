from __future__ import annotations

from app.domain.states import (
    CALL_STATE_RANK,
    TERMINAL_CALL_STATES,
    AgentState,
    CallState,
)

AGENT_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.OFFLINE: frozenset({AgentState.AVAILABLE}),
    AgentState.AVAILABLE: frozenset(
        {AgentState.OFFLINE, AgentState.PAUSED, AgentState.RESERVED}
    ),
    AgentState.PAUSED: frozenset({AgentState.AVAILABLE, AgentState.OFFLINE}),
    AgentState.RESERVED: frozenset(
        {AgentState.AVAILABLE, AgentState.DIALING, AgentState.OFFLINE}
    ),
    AgentState.DIALING: frozenset(
        {AgentState.CONNECTED, AgentState.AVAILABLE, AgentState.WRAP_UP}
    ),
    AgentState.CONNECTED: frozenset({AgentState.WRAP_UP}),
    AgentState.WRAP_UP: frozenset({AgentState.AVAILABLE, AgentState.PAUSED}),
}

CALL_TRANSITIONS: dict[CallState, frozenset[CallState]] = {
    CallState.QUEUED: frozenset({CallState.RESERVED, CallState.CANCELLED, CallState.FAILED}),
    CallState.RESERVED: frozenset(
        {CallState.INITIATED, CallState.FAILED, CallState.CANCELLED}
    ),
    CallState.INITIATED: frozenset(
        {CallState.RINGING, CallState.FAILED, CallState.CANCELLED}
    ),
    CallState.RINGING: frozenset(
        {CallState.ANSWERED, CallState.FAILED, CallState.CANCELLED}
    ),
    CallState.ANSWERED: frozenset({CallState.CONNECTED, CallState.ABANDONED}),
    CallState.CONNECTED: frozenset({CallState.COMPLETED, CallState.FAILED}),
    CallState.COMPLETED: frozenset(),
    CallState.FAILED: frozenset(),
    CallState.CANCELLED: frozenset(),
    CallState.ABANDONED: frozenset(),
}


class IllegalTransition(ValueError):
    pass


def assert_agent_transition(current: AgentState | str, new: AgentState | str) -> None:
    cur = AgentState(current)
    nxt = AgentState(new)
    if nxt not in AGENT_TRANSITIONS.get(cur, frozenset()):
        raise IllegalTransition(f"agent {cur} -> {nxt}")


def assert_call_transition(current: CallState | str, new: CallState | str) -> None:
    cur = CallState(current)
    nxt = CallState(new)
    if nxt not in CALL_TRANSITIONS.get(cur, frozenset()):
        raise IllegalTransition(f"call {cur} -> {nxt}")


def call_rank(state: CallState | str) -> int:
    return CALL_STATE_RANK[CallState(state)]


def is_terminal(state: CallState | str) -> bool:
    return CallState(state) in TERMINAL_CALL_STATES


def can_project(current: CallState | str, proposed: CallState | str) -> bool:
    """Rank-monotonic forward move; terminals absorb."""
    if is_terminal(current):
        return False
    return call_rank(proposed) > call_rank(current)
