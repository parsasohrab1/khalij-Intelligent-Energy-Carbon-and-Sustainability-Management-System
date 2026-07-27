"""E11 — multi-site registry (thin tenancy over plants)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Plant, Site


async def ensure_e11_schema(session: AsyncSession) -> None:
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS sites (
            id          SERIAL PRIMARY KEY,
            code        TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL,
            region      TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "ALTER TABLE plants ADD COLUMN IF NOT EXISTS site_id INTEGER REFERENCES sites(id)",
    ]
    for stmt in stmts:
        try:
            await session.execute(text(stmt))
        except Exception:
            await session.rollback()
            return
    await session.commit()


async def seed_default_site(session: AsyncSession, settings: Settings | None = None) -> Site:
    cfg = settings or get_settings()
    await ensure_e11_schema(session)
    existing = (
        await session.execute(select(Site).where(Site.code == cfg.site_code))
    ).scalar_one_or_none()
    if existing is None:
        existing = Site(code=cfg.site_code, name=cfg.site_name, region="gulf")
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
    # Assign plants without site
    plants = list((await session.execute(select(Plant))).scalars().all())
    changed = False
    for p in plants:
        if getattr(p, "site_id", None) is None:
            p.site_id = existing.id
            changed = True
    if changed:
        await session.commit()
    return existing


@dataclass
class SiteInfo:
    code: str
    name: str
    region: str | None
    plants: list[dict[str, str]]


async def list_sites(session: AsyncSession) -> list[SiteInfo]:
    await seed_default_site(session)
    sites = list((await session.execute(select(Site).order_by(Site.code))).scalars().all())
    out: list[SiteInfo] = []
    for s in sites:
        plants = list(
            (
                await session.execute(select(Plant).where(Plant.site_id == s.id).order_by(Plant.code))
            ).scalars().all()
        )
        # Fallback: if no site_id linkage yet, attach all plants to default site
        if not plants and s.code == get_settings().site_code:
            plants = list((await session.execute(select(Plant).order_by(Plant.code))).scalars().all())
        out.append(
            SiteInfo(
                code=s.code,
                name=s.name,
                region=s.region,
                plants=[{"code": p.code, "name": p.name, "unit_type": p.unit_type} for p in plants],
            )
        )
    return out


async def get_site(session: AsyncSession, code: str) -> SiteInfo | None:
    for s in await list_sites(session):
        if s.code == code:
            return s
    return None
