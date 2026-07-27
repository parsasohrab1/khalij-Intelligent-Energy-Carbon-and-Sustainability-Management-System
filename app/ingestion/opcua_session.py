"""Long-lived OPC-UA session with subscription cache (E6 Plant Connect)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.ingestion.quality import QualityCode, status_code_to_quality
from app.ingestion.tag_map import SENSOR_FIELDS, PlantTagMap, get_tag_map

logger = logging.getLogger(__name__)


@dataclass
class TagSample:
    value: float | None
    quality: QualityCode
    status_code: int | None
    server_timestamp: datetime | None
    source_timestamp: datetime | None


@dataclass
class PlantConnectSession:
    """
    Keeps one asyncua Client open and optionally a subscription.
    Falls back to polled DataValue reads when subscription is disabled.
    """

    settings: Settings
    _client: Any = None
    _subscription: Any = None
    _handles: dict[str, int] = field(default_factory=dict)
    _cache: dict[str, dict[str, TagSample]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _connected: bool = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        async with self._lock:
            if self._connected:
                return
            if not self.settings.opc_ua_endpoint:
                raise RuntimeError("OPC_UA_ENDPOINT is required for plant connect")
            try:
                from asyncua import Client
            except ImportError as exc:
                raise RuntimeError(
                    "OPC-UA mode requires asyncua. Install with: pip install 'iems[opcua]'"
                ) from exc

            client = Client(url=self.settings.opc_ua_endpoint)
            if self.settings.opc_ua_username:
                client.set_user(self.settings.opc_ua_username)
                client.set_password(self.settings.opc_ua_password or "")
            await client.connect()
            self._client = client
            self._connected = True
            logger.info("OPC-UA connected → %s", self.settings.opc_ua_endpoint)

            if self.settings.opc_ua_use_subscription:
                await self._setup_subscriptions()

    async def _setup_subscriptions(self) -> None:
        assert self._client is not None
        plants = get_tag_map()
        handler = _SubscriptionHandler(self)
        period_ms = max(100, int(1000 / max(self.settings.ingestion_rate_hz, 0.1)))
        self._subscription = await self._client.create_subscription(period_ms, handler)
        for plant_code, plant in plants.items():
            self._cache.setdefault(plant_code, {})
            for field in SENSOR_FIELDS:
                tag = plant.tags.get(field)
                if tag is None:
                    continue
                node = self._client.get_node(tag.node_id)
                handle = await self._subscription.subscribe_data_change(node)
                self._handles[f"{plant_code}:{field}:{handle}"] = handle
                # Seed with one read
                sample = await self._read_datavalue(node)
                self._cache[plant_code][field] = sample

    async def disconnect(self) -> None:
        async with self._lock:
            if self._subscription is not None:
                try:
                    await self._subscription.delete()
                except Exception:  # noqa: BLE001
                    logger.exception("OPC subscription delete failed")
                self._subscription = None
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except Exception:  # noqa: BLE001
                    logger.exception("OPC disconnect failed")
                self._client = None
            self._connected = False
            self._handles.clear()

    async def ensure(self) -> None:
        if not self._connected:
            await self.connect()

    async def _read_datavalue(self, node: Any) -> TagSample:
        try:
            dv = await node.read_data_value()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OPC read_data_value failed: %s", exc)
            return TagSample(None, QualityCode.BAD, None, None, None)

        status = None
        try:
            status = int(dv.StatusCode.value) if dv.StatusCode is not None else None
        except Exception:  # noqa: BLE001
            status = None
        quality = status_code_to_quality(status)
        value = None
        try:
            if dv.Value is not None and dv.Value.Value is not None:
                value = float(dv.Value.Value)
        except (TypeError, ValueError):
            quality = QualityCode.BAD
            value = None

        server_ts = getattr(dv, "ServerTimestamp", None)
        source_ts = getattr(dv, "SourceTimestamp", None)
        if server_ts is not None and getattr(server_ts, "tzinfo", None) is None:
            server_ts = server_ts.replace(tzinfo=timezone.utc)
        if source_ts is not None and getattr(source_ts, "tzinfo", None) is None:
            source_ts = source_ts.replace(tzinfo=timezone.utc)

        return TagSample(value, quality, status, server_ts, source_ts)

    async def read_plant(self, plant: PlantTagMap) -> dict[str, TagSample]:
        await self.ensure()
        assert self._client is not None

        if self.settings.opc_ua_use_subscription and plant.code in self._cache:
            cached = self._cache.get(plant.code, {})
            if len(cached) >= len([f for f in SENSOR_FIELDS if f in plant.tags]):
                return dict(cached)

        out: dict[str, TagSample] = {}
        for field in SENSOR_FIELDS:
            tag = plant.tags.get(field)
            if tag is None:
                continue
            node = self._client.get_node(tag.node_id)
            out[field] = await self._read_datavalue(node)
        self._cache[plant.code] = out
        return out

    def update_cache(self, node_id: str, sample: TagSample) -> None:
        """Map a subscription callback back to plant/field via node_id."""
        plants = get_tag_map()
        for plant_code, plant in plants.items():
            for field, tag in plant.tags.items():
                if tag.node_id == node_id:
                    self._cache.setdefault(plant_code, {})[field] = sample
                    return


class _SubscriptionHandler:
    def __init__(self, session: PlantConnectSession) -> None:
        self.session = session

    def datachange_notification(self, node, val, data) -> None:  # noqa: ANN001
        try:
            node_id = node.nodeid.to_string() if hasattr(node, "nodeid") else str(node)
            status = None
            quality = QualityCode.GOOD
            server_ts = None
            source_ts = None
            if data is not None and getattr(data, "monitored_item", None) is not None:
                dv = data.monitored_item.Value
                try:
                    status = int(dv.StatusCode.value) if dv.StatusCode is not None else None
                except Exception:  # noqa: BLE001
                    status = None
                quality = status_code_to_quality(status)
                server_ts = getattr(dv, "ServerTimestamp", None)
                source_ts = getattr(dv, "SourceTimestamp", None)
            try:
                value = float(val) if val is not None else None
            except (TypeError, ValueError):
                value = None
                quality = QualityCode.BAD
            sample = TagSample(value, quality, status, server_ts, source_ts)
            self.session.update_cache(node_id, sample)
        except Exception:  # noqa: BLE001
            logger.exception("OPC subscription callback failed")


_SESSION: PlantConnectSession | None = None


def get_plant_session(settings: Settings | None = None) -> PlantConnectSession:
    global _SESSION
    cfg = settings or get_settings()
    if _SESSION is None or _SESSION.settings.opc_ua_endpoint != cfg.opc_ua_endpoint:
        _SESSION = PlantConnectSession(settings=cfg)
    return _SESSION


async def close_plant_session() -> None:
    global _SESSION
    if _SESSION is not None:
        await _SESSION.disconnect()
        _SESSION = None
