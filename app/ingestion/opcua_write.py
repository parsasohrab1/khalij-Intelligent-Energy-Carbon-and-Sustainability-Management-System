"""E9 — allowlisted OPC-UA setpoint writes (dry-run by default)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.ingestion.tag_map import TagDef, get_tag_map

logger = logging.getLogger(__name__)


class WriteNotAllowedError(RuntimeError):
    """Raised when live write is blocked by config / allowlist."""


@dataclass
class WritePlanItem:
    field: str
    node_id: str
    value: float
    engineering_value: float
    scale: float
    offset: float


@dataclass
class WriteResult:
    dry_run: bool
    plant_code: str
    planned: list[WritePlanItem] = field(default_factory=list)
    written: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    detail: str = ""


def _write_node(tag: TagDef) -> str:
    return tag.write_node_id or tag.node_id


def plan_setpoint_writes(
    plant_code: str,
    proposed: dict[str, float],
    *,
    settings: Settings | None = None,
) -> WriteResult:
    """Build allowlisted write plan from proposed setpoints (no I/O)."""
    cfg = settings or get_settings()
    plants = get_tag_map()
    plant = plants.get(plant_code)
    if plant is None:
        raise WriteNotAllowedError(f"Unknown plant '{plant_code}' in tag map")

    allowed = set(cfg.writable_field_list)
    planned: list[WritePlanItem] = []
    skipped: list[str] = []
    for field_name, raw_value in proposed.items():
        if field_name not in allowed:
            skipped.append(f"{field_name}:not_in_writable_fields")
            continue
        tag = plant.tags.get(field_name)
        if tag is None:
            skipped.append(f"{field_name}:no_tag")
            continue
        if not tag.writable:
            skipped.append(f"{field_name}:tag_not_writable")
            continue
        eng = float(raw_value)
        # invert scale/offset when writing raw PLC units: raw = (eng - offset) / scale
        scale = tag.scale if tag.scale else 1.0
        raw = (eng - tag.offset) / scale
        planned.append(
            WritePlanItem(
                field=field_name,
                node_id=_write_node(tag),
                value=raw,
                engineering_value=eng,
                scale=scale,
                offset=tag.offset,
            )
        )
    return WriteResult(
        dry_run=True,
        plant_code=plant_code,
        planned=planned,
        skipped=skipped,
        detail="plan_only",
    )


async def write_setpoints(
    plant_code: str,
    proposed: dict[str, float],
    *,
    dry_run: bool | None = None,
    settings: Settings | None = None,
) -> WriteResult:
    """
    Apply proposed setpoints to OPC (or dry-run).
    Live writes require OPC_WRITE_ENABLED (+ typically PLANT_CONNECT).
    """
    cfg = settings or get_settings()
    plan = plan_setpoint_writes(plant_code, proposed, settings=cfg)
    do_dry = cfg.opc_write_dry_run_default if dry_run is None else bool(dry_run)

    if do_dry:
        plan.dry_run = True
        plan.detail = "dry_run — no OPC write performed"
        return plan

    if not cfg.opc_write_enabled:
        raise WriteNotAllowedError(
            "Live OPC write blocked: set OPC_WRITE_ENABLED=true after audit readiness"
        )
    if not cfg.opc_ua_endpoint:
        raise WriteNotAllowedError("OPC_UA_ENDPOINT required for live setpoint write")
    if not plan.planned:
        raise WriteNotAllowedError("No allowlisted writable setpoints to apply")

    try:
        from asyncua import Client, ua
    except ImportError as exc:
        raise WriteNotAllowedError(
            "asyncua required for live write: pip install 'iems[opcua]'"
        ) from exc

    written: list[dict[str, Any]] = []
    client = Client(url=cfg.opc_ua_endpoint)
    if cfg.opc_ua_username:
        client.set_user(cfg.opc_ua_username)
        client.set_password(cfg.opc_ua_password or "")
    await client.connect()
    try:
        for item in plan.planned:
            node = client.get_node(item.node_id)
            await node.write_value(ua.Variant(float(item.value), ua.VariantType.Float))
            written.append(
                {
                    "field": item.field,
                    "node_id": item.node_id,
                    "value": item.engineering_value,
                    "raw": item.value,
                }
            )
            logger.info(
                "OPC write plant=%s field=%s node=%s eng=%s",
                plant_code,
                item.field,
                item.node_id,
                item.engineering_value,
            )
    finally:
        await client.disconnect()

    return WriteResult(
        dry_run=False,
        plant_code=plant_code,
        planned=plan.planned,
        written=written,
        skipped=plan.skipped,
        detail="live_write_ok",
    )
