from __future__ import annotations

from typing import Any

from app.providers.port import CallStatus, InitiateResult
from app.settings import get_settings


class PlivoProvider:
    """Real Plivo adapter stub — disabled unless credentials are configured."""

    name = "plivo"

    def __init__(self) -> None:
        s = get_settings()
        self.auth_id = s.plivo_auth_id
        self.auth_token = s.plivo_auth_token

    @property
    def enabled(self) -> bool:
        return bool(self.auth_id and self.auth_token)

    async def initiate_call(
        self,
        *,
        to_number: str,
        from_number: str,
        webhook_url: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> InitiateResult:
        if not self.enabled:
            return InitiateResult("", False, "plivo_disabled")
        # Production would call Plivo REST here.
        return InitiateResult("", False, "plivo_not_wired_in_prototype")

    async def hangup(self, provider_call_id: str) -> None:
        return None

    async def get_status(self, provider_call_id: str) -> CallStatus:
        return CallStatus(provider_call_id, "unknown", {})

    async def play_safe_harbour(self, provider_call_id: str) -> None:
        return None
