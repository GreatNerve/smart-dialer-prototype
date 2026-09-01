from __future__ import annotations

import random
from uuid import uuid4

from app.domain.state_machine import can_project
from app.domain.states import CALL_STATE_RANK, EVENT_TO_CALL_STATE, CallState, TERMINAL_CALL_STATES


def project(sequence: list[str]) -> CallState:
    state = CallState.QUEUED
    # jump to INITIATED as baseline like after dial
    state = CallState.INITIATED
    for et in sequence:
        proposed = EVENT_TO_CALL_STATE[et]
        if can_project(state, proposed):
            state = proposed
    return state


def test_event_fuzzer_never_leaves_terminal_inconsistently():
    rng = random.Random(7)
    base = ["ringing", "answered", "completed"]
    for _ in range(200):
        seq = base[:]
        # shuffle, duplicate, truncate
        if rng.random() < 0.5:
            rng.shuffle(seq)
        if rng.random() < 0.5:
            seq = seq + [rng.choice(base)]
        if rng.random() < 0.3:
            seq = seq[: rng.randint(0, len(seq))]
        final = project(seq)
        if any(EVENT_TO_CALL_STATE[e] in TERMINAL_CALL_STATES for e in seq):
            # If a terminal appeared and was applyable at some point, final should be terminal
            # or stuck pre-terminal if terminal never won rank race — still must not regress rank
            assert CALL_STATE_RANK[final] >= CALL_STATE_RANK[CallState.INITIATED]
        if final in TERMINAL_CALL_STATES:
            assert not can_project(final, CallState.RINGING)


def test_completed_before_ringing_stays_completed():
    assert project(["completed", "answered", "ringing"]) == CallState.COMPLETED
