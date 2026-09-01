from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class InitiateResult:
    provider_call_id: str
    accepted: bool
    error: str | None = None


@dataclass
class CallStatus:
    provider_call_id: str
    state: str
    raw: dict[str, Any]


class TelecomProvider(Protocol):
    name: str

    async def initiate_call(
        self,
        *,
        to_number: str,
        from_number: str,
        webhook_url: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> InitiateResult: ...

    async def hangup(self, provider_call_id: str) -> None: ...

    async def get_status(self, provider_call_id: str) -> CallStatus: ...

    async def play_safe_harbour(self, provider_call_id: str) -> None: ...
