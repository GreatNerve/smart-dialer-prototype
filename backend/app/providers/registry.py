from __future__ import annotations

from app.providers.http_mock import HttpMockProvider
from app.providers.plivo import PlivoProvider
from app.providers.port import TelecomProvider
from app.settings import get_settings


def get_provider(name: str) -> TelecomProvider:
    settings = get_settings()
    if name == "plivo":
        return PlivoProvider()
    if name in {"mock_a", "a"}:
        return HttpMockProvider("mock_a", settings.mock_telco_url)
    if name in {"mock_b", "b"}:
        return HttpMockProvider("mock_b", settings.mock_telco_url)
    return HttpMockProvider(name, settings.mock_telco_url)
