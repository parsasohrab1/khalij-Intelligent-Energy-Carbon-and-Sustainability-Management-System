"""Shared application state and lifespan helpers."""

from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings


@dataclass
class AppState:
    settings: Settings = field(default_factory=get_settings)
    engine: AsyncEngine | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    redis: Redis | None = None
    extras: dict[str, Any] = field(default_factory=dict)


state = AppState()


async def init_db(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    state.engine = create_async_engine(cfg.database_url, echo=cfg.app_debug, pool_pre_ping=True)
    state.session_factory = async_sessionmaker(state.engine, expire_on_commit=False)


async def close_db() -> None:
    if state.engine is not None:
        await state.engine.dispose()
        state.engine = None
        state.session_factory = None


async def init_redis(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    state.redis = Redis.from_url(cfg.redis_url, decode_responses=True)


async def close_redis() -> None:
    if state.redis is not None:
        await state.redis.aclose()
        state.redis = None
