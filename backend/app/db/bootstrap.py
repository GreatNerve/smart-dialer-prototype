from __future__ import annotations

from tortoise import Tortoise

from app.db.config import TORTOISE_ORM


async def init_db(*, generate_schemas: bool = True) -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    if generate_schemas:
        await Tortoise.generate_schemas()


async def close_db() -> None:
    await Tortoise.close_connections()
