from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any, Awaitable, Callable

from app.providers.port import CallStatus, InitiateResult

WebhookCallback = Callable[[dict[str, Any]], Awaitable[None]]


class InProcessFakeProvider:
    """Deterministic fake for tests — invokes webhook callback directly."""

    def __init__(
        self,
        name: str = "fake",
        *,
        answer_rate: float = 0.5,
        seed: int = 42,
        duplicate: bool = False,
        out_of_order: bool = False,
        fail_rate: float = 0.0,
        on_event: WebhookCallback | None = None,
        time_scale: float = 60.0,
    ) -> None:
        self.name = name
        self.answer_rate = answer_rate
        self.rng = random.Random(seed)
        self.duplicate = duplicate
        self.out_of_order = out_of_order
        self.fail_rate = fail_rate
        self.on_event = on_event
        self.time_scale = max(time_scale, 1.0)
        self._calls: dict[str, str] = {}

    async def initiate_call(
        self,
        *,
        to_number: str,
        from_number: str,
        webhook_url: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> InitiateResult:
        if self.rng.random() < self.fail_rate:
            return InitiateResult("", False, "simulated_failure")
        call_id = f"fake-{uuid.uuid4()}"
        self._calls[call_id] = "initiated"
        asyncio.create_task(self._lifecycle(call_id, metadata))
        return InitiateResult(call_id, True)

    async def _emit(self, call_id: str, event_type: str, extra: dict | None = None) -> None:
        event_id = str(uuid.uuid4())
        payload = {
            "event_id": event_id,
            "call_id": call_id,
            "type": event_type,
            **(extra or {}),
        }
        if self.on_event:
            await self.on_event(payload)
            if self.duplicate:
                await self.on_event(payload)

    async def _lifecycle(self, call_id: str, metadata: dict[str, Any]) -> None:
        scale = self.time_scale
        await asyncio.sleep(0.05 / scale * 60)
        events = ["ringing"]
        answered = self.rng.random() < self.answer_rate
        if answered:
            events += ["answered", "completed"]
        else:
            events += ["failed"]
        if self.out_of_order and len(events) > 1:
            shuffled = events[:]
            self.rng.shuffle(shuffled)
            events = shuffled
        for et in events:
            self._calls[call_id] = et
            await self._emit(call_id, et)
            await asyncio.sleep(0.1 / scale * 60)

    async def hangup(self, provider_call_id: str) -> None:
        self._calls[provider_call_id] = "cancelled"

    async def get_status(self, provider_call_id: str) -> CallStatus:
        return CallStatus(provider_call_id, self._calls.get(provider_call_id, "unknown"), {})

    async def play_safe_harbour(self, provider_call_id: str) -> None:
        await self._emit(provider_call_id, "completed", {"safe_harbour": True})
