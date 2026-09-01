from __future__ import annotations

from typing import Any

import httpx

from app.providers.port import CallStatus, InitiateResult


class HttpMockProvider:
    def __init__(self, name: str, base_url: str) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")

    async def initiate_call(
        self,
        *,
        to_number: str,
        from_number: str,
        webhook_url: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> InitiateResult:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                r = await client.post(
                    f"{self.base_url}/calls",
                    json={
                        "to": to_number,
                        "from": from_number,
                        "webhook_url": webhook_url,
                        "idempotency_key": idempotency_key,
                        "profile": self.name.replace("mock_", ""),
                        "metadata": metadata,
                    },
                )
                r.raise_for_status()
                data = r.json()
                return InitiateResult(data["call_id"], True)
            except Exception as exc:  # noqa: BLE001
                return InitiateResult("", False, str(exc))

    async def hangup(self, provider_call_id: str) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{self.base_url}/calls/{provider_call_id}/hangup")

    async def get_status(self, provider_call_id: str) -> CallStatus:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{self.base_url}/calls/{provider_call_id}")
            data = r.json()
            return CallStatus(provider_call_id, data.get("state", "unknown"), data)

    async def play_safe_harbour(self, provider_call_id: str) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{self.base_url}/calls/{provider_call_id}/safe-harbour")
