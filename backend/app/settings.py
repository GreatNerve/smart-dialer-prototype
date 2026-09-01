from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgres://dialer:dialer@localhost:5432/dialer"
    mock_telco_url: str = "http://localhost:8001"
    webhook_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173"
    worker_id: str = "worker-local"
    lease_ttl_seconds: int = 20
    pacing_tick_seconds: float = 1.0
    reaper_interval_seconds: float = 2.0
    circuit_error_threshold: float = 0.35
    circuit_cooldown_seconds: float = 30.0
    plivo_auth_id: str = ""
    plivo_auth_token: str = ""
    chaos_kill_worker: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
