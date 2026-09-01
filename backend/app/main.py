from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from app.api.routes import router
from app.db.config import TORTOISE_ORM
from app.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(
        app,
        config=TORTOISE_ORM,
        generate_schemas=True,
        add_exception_handlers=True,
    ):
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SmartDialer", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list + ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    from app.api.stream import stream_router

    app.include_router(stream_router)

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app


app = create_app()
