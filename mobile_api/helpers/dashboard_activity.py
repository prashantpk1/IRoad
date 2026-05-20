"""
mobile_api/helpers/dashboard_activity.py

Constants and helpers for the driver dashboard activity feed.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from django.conf import settings
from django.utils import timezone

ACTIVITY_TYPE_ACTION = 'action'
ACTIVITY_TYPE_SHIPMENT = 'shipment'
ACTIVITY_TYPE_MOVEMENT = 'movement'
ACTIVITY_TYPE_POD = 'pod'

ACTIVITY_TYPES = (
    ACTIVITY_TYPE_ACTION,
    ACTIVITY_TYPE_SHIPMENT,
    ACTIVITY_TYPE_MOVEMENT,
    ACTIVITY_TYPE_POD,
)

DEFAULT_ACTIVITY_LIMIT_FULL = 10
DEFAULT_ACTIVITY_LIMIT_SUMMARY = 5
MAX_ACTIVITY_LIMIT = 10
MIN_ACTIVITY_LIMIT = 1


def clamp_activity_limit(value: int | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(MIN_ACTIVITY_LIMIT, min(MAX_ACTIVITY_LIMIT, parsed))


def resolve_activity_limit_from_settings(*, variant: str = 'full') -> int:
    if variant == 'summary':
        return clamp_activity_limit(
            getattr(settings, 'MOBILE_API_DASHBOARD_SUMMARY_RECENT_ACTIVITY_LIMIT', 5),
            default=DEFAULT_ACTIVITY_LIMIT_SUMMARY,
        )
    return clamp_activity_limit(
        getattr(settings, 'MOBILE_API_DASHBOARD_RECENT_ACTIVITY_LIMIT', 10),
        default=DEFAULT_ACTIVITY_LIMIT_FULL,
    )


def per_source_fetch_cap(total_limit: int) -> int:
    """Rows to pull from each source before merge (bounded, not full history)."""
    return max(MIN_ACTIVITY_LIMIT, min(MAX_ACTIVITY_LIMIT, total_limit))


def to_sort_datetime(value: datetime | date | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.utc)
        return value
    return timezone.make_aware(datetime.combine(value, time.min), timezone.utc)


def iso_timestamp(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        value = timezone.make_aware(datetime.combine(value, time.min), timezone.utc)
    if isinstance(value, datetime):
        return value.isoformat().replace('+00:00', 'Z')
    return None
