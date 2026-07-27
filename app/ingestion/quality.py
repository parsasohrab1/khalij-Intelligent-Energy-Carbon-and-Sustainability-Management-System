"""OPC-UA data quality codes (E6 Plant Connect)."""

from __future__ import annotations

from enum import Enum
from typing import Any


class QualityCode(str, Enum):
    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"
    UNKNOWN = "unknown"


# OPC UA StatusCode high bits (simplified, UA Part 4)
_QUALITY_MASK = 0xC0000000
_GOOD = 0x00000000
_UNCERTAIN = 0x40000000
_BAD = 0x80000000


def status_code_to_quality(status_code: int | None) -> QualityCode:
    """Map OPC UA StatusCode integer to Good / Uncertain / Bad."""
    if status_code is None:
        return QualityCode.UNKNOWN
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return QualityCode.UNKNOWN
    bits = code & _QUALITY_MASK
    if bits == _GOOD:
        return QualityCode.GOOD
    if bits == _UNCERTAIN:
        return QualityCode.UNCERTAIN
    if bits == _BAD:
        return QualityCode.BAD
    return QualityCode.UNKNOWN


def aggregate_quality(qualities: dict[str, str | QualityCode]) -> QualityCode:
    """Worst-of aggregation across tags (Bad > Uncertain > Unknown > Good)."""
    order = {
        QualityCode.BAD: 3,
        QualityCode.UNCERTAIN: 2,
        QualityCode.UNKNOWN: 1,
        QualityCode.GOOD: 0,
    }
    worst = QualityCode.GOOD
    for q in qualities.values():
        code = QualityCode(q) if not isinstance(q, QualityCode) else q
        if order[code] > order[worst]:
            worst = code
    return worst


def quality_is_healthy(quality: str | QualityCode, *, allow_uncertain: bool = True) -> bool:
    code = QualityCode(quality) if not isinstance(quality, QualityCode) else quality
    if code == QualityCode.GOOD:
        return True
    if code == QualityCode.UNCERTAIN and allow_uncertain:
        return True
    return False


def apply_scale(value: float, *, scale: float = 1.0, offset: float = 0.0) -> float:
    return value * scale + offset


def reading_quality_payload(
    per_tag: dict[str, QualityCode | str],
    *,
    allow_uncertain: bool = True,
) -> dict[str, Any]:
    overall = aggregate_quality(per_tag)
    return {
        "quality": overall.value,
        "quality_detail": {k: (v.value if isinstance(v, QualityCode) else v) for k, v in per_tag.items()},
        "quality_ok": quality_is_healthy(overall, allow_uncertain=allow_uncertain),
    }
