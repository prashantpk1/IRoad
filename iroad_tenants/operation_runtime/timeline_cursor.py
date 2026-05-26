"""
Keyset cursor pagination for driver job execution timelines (action logs).

Ordering: ``-log_date``, ``-created_at``, ``-log_id`` (newest first).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from uuid import UUID

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime


@dataclass(frozen=True)
class TimelineCursor:
    log_date: str
    log_id: str


def _encode_payload(payload: dict) -> str:
    raw = json.dumps(payload, separators=(',', ':'), default=str).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _decode_payload(token: str) -> dict | None:
    try:
        pad = '=' * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + pad).encode('ascii'))
        data = json.loads(raw.decode('utf-8'))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _dt_iso(value) -> str:
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _parse_dt(value: str | None):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def encode_cursor_from_log(log_row) -> str | None:
    if log_row is None:
        return None
    log_id = getattr(log_row, 'log_id', None)
    log_date = getattr(log_row, 'log_date', None)
    if not log_id or log_date is None:
        return None
    return _encode_payload(
        {
            'v': 1,
            'log_date': _dt_iso(log_date),
            'log_id': str(log_id),
        }
    )


def parse_timeline_cursor_param(request) -> TimelineCursor | None:
    if request is None:
        return None
    params = getattr(request, 'query_params', None) or {}
    token = (params.get('cursor') or '').strip()
    if not token:
        return None
    data = _decode_payload(token)
    if not data or data.get('v') != 1:
        return None
    log_date = str(data.get('log_date') or '').strip()
    log_id = str(data.get('log_id') or '').strip()
    if not log_date or not log_id:
        return None
    try:
        UUID(log_id)
    except ValueError:
        return None
    if _parse_dt(log_date) is None:
        return None
    return TimelineCursor(log_date=log_date, log_id=log_id)


def apply_timeline_cursor_filter(queryset, cursor: TimelineCursor):
    """Continue older page (strictly before cursor row)."""
    anchor_dt = _parse_dt(cursor.log_date)
    if anchor_dt is None:
        return queryset.filter(log_id__lt=cursor.log_id)
    return queryset.filter(
        Q(log_date__lt=anchor_dt)
        | Q(log_date=anchor_dt, log_id__lt=cursor.log_id)
    )
