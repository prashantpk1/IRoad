"""
mobile_api/helpers/job_list_cursor.py

Stable keyset (cursor) pagination for driver job list feeds.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger('mobile_api.jobs')

JobListEntityType = Literal['shipment', 'movement']
PaginationMode = Literal['cursor', 'offset']


@dataclass(frozen=True)
class JobListCursor:
    sort: str
    entity_type: str
    pk: str
    updated_at: str | None = None
    created_at: str | None = None
    priority: int | None = None
    number: str | None = None
    status: str | None = None


def job_list_default_pagination_mode() -> PaginationMode:
    raw = (getattr(settings, 'MOBILE_API_JOBS_DEFAULT_PAGINATION', 'cursor') or 'cursor').strip().lower()
    return 'offset' if raw == 'offset' else 'cursor'


def resolve_pagination_mode(request) -> PaginationMode:
    """``cursor`` param forces keyset mode; ``page`` only when offset allowed; else cursor."""
    from mobile_api.helpers.job_list_guards import offset_pagination_allowed

    if request is None:
        return job_list_default_pagination_mode()
    params = getattr(request, 'query_params', None) or {}
    if (params.get('cursor') or '').strip():
        return 'cursor'
    if (params.get('page') or '').strip():
        if offset_pagination_allowed():
            return 'offset'
        return 'cursor'
    return job_list_default_pagination_mode()


def _pk_field(entity_type: str) -> str:
    return 'shipment_id' if entity_type == 'shipment' else 'movement_id'


def _row_pk(row, entity_type: str):
    field = _pk_field(entity_type)
    return getattr(row, field, None) or getattr(row, 'pk', None)


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


def encode_cursor_from_row(row, *, entity_type: str, sort: str) -> str | None:
    """Build opaque cursor from the last row on a page."""
    pk = _row_pk(row, entity_type)
    if not pk:
        return None
    payload: dict[str, Any] = {
        'v': 1,
        'sort': sort,
        'entity': entity_type,
        'pk': str(pk),
    }
    updated = getattr(row, 'updated_at', None)
    created = getattr(row, 'created_at', None)
    if updated is not None:
        payload['updated_at'] = _dt_iso(updated)
    if created is not None:
        payload['created_at'] = _dt_iso(created)
    if sort == 'priority_desc':
        payload['priority'] = int(
            getattr(row, 'mobile_operational_rank', None)
            or getattr(row, '_job_priority', 10)
            or 10
        )
    if sort in ('number_desc', 'number_asc'):
        no_field = 'shipment_no' if entity_type == 'shipment' else 'movement_no'
        payload['number'] = str(getattr(row, no_field, '') or '')
    if sort == 'status_asc':
        status_field = 'shipment_status' if entity_type == 'shipment' else 'status'
        payload['status'] = str(getattr(row, status_field, '') or '')
    return _encode_payload(payload)


def parse_cursor_param(request, *, entity_type: str) -> JobListCursor | None:
    if request is None:
        return None
    params = getattr(request, 'query_params', None) or {}
    token = (params.get('cursor') or '').strip()
    if not token:
        return None
    data = _decode_payload(token)
    if not data or data.get('v') != 1:
        return None
    if data.get('entity') != entity_type:
        return None
    sort = str(data.get('sort') or 'updated_desc')
    pk = str(data.get('pk') or '')
    if not pk:
        return None
    try:
        UUID(pk)
    except ValueError:
        return None
    return JobListCursor(
        sort=sort,
        entity_type=entity_type,
        pk=pk,
        updated_at=data.get('updated_at'),
        created_at=data.get('created_at'),
        priority=data.get('priority'),
        number=data.get('number'),
        status=data.get('status'),
    )


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


def apply_cursor_filter(
    queryset: QuerySet,
    *,
    entity_type: str,
    sort: str,
    cursor: JobListCursor,
) -> QuerySet:
    """
    Keyset filter for stable continuation (no OFFSET).

    Tie-breaker is always primary key (UUID) to avoid duplicates/skips on updates.
    """
    pk_field = _pk_field(entity_type)
    pk_val = cursor.pk

    if sort == 'updated_desc':
        ua = _parse_dt(cursor.updated_at)
        if ua is None:
            return queryset.filter(**{f'{pk_field}__lt': pk_val})
        return queryset.filter(
            Q(updated_at__lt=ua)
            | Q(updated_at=ua, **{f'{pk_field}__lt': pk_val}),
        )

    if sort == 'updated_asc':
        ua = _parse_dt(cursor.updated_at)
        if ua is None:
            return queryset.filter(**{f'{pk_field}__gt': pk_val})
        return queryset.filter(
            Q(updated_at__gt=ua)
            | Q(updated_at=ua, **{f'{pk_field}__gt': pk_val}),
        )

    if sort == 'created_desc':
        ca = _parse_dt(cursor.created_at)
        if ca is None:
            return queryset.filter(**{f'{pk_field}__lt': pk_val})
        return queryset.filter(
            Q(created_at__lt=ca)
            | Q(created_at=ca, **{f'{pk_field}__lt': pk_val}),
        )

    if sort == 'priority_desc' and entity_type == 'shipment':
        pr = cursor.priority if cursor.priority is not None else 10
        ua = _parse_dt(cursor.updated_at)
        clauses = Q(mobile_operational_rank__gt=pr)
        if ua is not None:
            clauses |= Q(
                mobile_operational_rank=pr,
                updated_at__lt=ua,
            )
            clauses |= Q(
                mobile_operational_rank=pr,
                updated_at=ua,
                **{f'{pk_field}__lt': pk_val},
            )
        else:
            clauses |= Q(mobile_operational_rank=pr, **{f'{pk_field}__lt': pk_val})
        return queryset.filter(clauses)

    if sort in ('number_desc', 'number_asc') and cursor.number is not None:
        no_field = 'shipment_no' if entity_type == 'shipment' else 'movement_no'
        op = 'lt' if sort == 'number_desc' else 'gt'
        return queryset.filter(
            Q(**{f'{no_field}__{op}': cursor.number})
            | Q(**{no_field: cursor.number, f'{pk_field}__lt': pk_val}),
        )

    if sort == 'status_asc' and cursor.status is not None:
        status_field = 'shipment_status' if entity_type == 'shipment' else 'status'
        return queryset.filter(
            Q(**{f'{status_field}__gt': cursor.status})
            | Q(**{status_field: cursor.status, f'{pk_field}__lt': pk_val}),
        )

    logger.warning('jobs.cursor fallback filter sort=%s entity=%s', sort, entity_type)
    return queryset.filter(**{f'{pk_field}__lt': pk_val})
