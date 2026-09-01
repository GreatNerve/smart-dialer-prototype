from __future__ import annotations

import os

from app.settings import get_settings

_settings = get_settings()

TORTOISE_ORM = {
    "connections": {
        "default": os.getenv("DATABASE_URL", _settings.database_url),
    },
    "apps": {
        "models": {
            "models": ["app.domain.models", "tortoise.migrations.models"],
            "default_connection": "default",
        }
    },
    "use_tz": True,
    "timezone": "UTC",
}
