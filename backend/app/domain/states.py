from __future__ import annotations

from enum import StrEnum


class AgentState(StrEnum):
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DIALING = "DIALING"
    CONNECTED = "CONNECTED"
    WRAP_UP = "WRAP_UP"
    PAUSED = "PAUSED"


class CallState(StrEnum):
    QUEUED = "QUEUED"
    RESERVED = "RESERVED"
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    CONNECTED = "CONNECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"


# Higher rank wins; terminals share 100 and are absorbing.
CALL_STATE_RANK: dict[CallState, int] = {
    CallState.QUEUED: 10,
    CallState.RESERVED: 20,
    CallState.INITIATED: 30,
    CallState.RINGING: 40,
    CallState.ANSWERED: 50,
    CallState.CONNECTED: 60,
    CallState.COMPLETED: 100,
    CallState.FAILED: 100,
    CallState.CANCELLED: 100,
    CallState.ABANDONED: 100,
}

TERMINAL_CALL_STATES = frozenset(
    {
        CallState.COMPLETED,
        CallState.FAILED,
        CallState.CANCELLED,
        CallState.ABANDONED,
    }
)

AGENT_BOUND_CALL_STATES = frozenset(
    {
        CallState.RESERVED,
        CallState.INITIATED,
        CallState.RINGING,
        CallState.ANSWERED,
        CallState.CONNECTED,
    }
)

EVENT_TO_CALL_STATE: dict[str, CallState] = {
    "initiated": CallState.INITIATED,
    "ringing": CallState.RINGING,
    "answered": CallState.ANSWERED,
    "completed": CallState.COMPLETED,
    "failed": CallState.FAILED,
    "cancelled": CallState.CANCELLED,
}
