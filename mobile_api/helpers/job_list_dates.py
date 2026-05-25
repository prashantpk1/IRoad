"""
mobile_api/helpers/job_list_dates.py

Validated date-range filters for driver job list feeds (index-friendly).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from django.db.models import Q, QuerySet
from django.utils import timezone

JobListDateField = Literal['updated', 'operational']

VALID_DATE_FIELDS: frozenset[str] = frozenset({'updated', 'operational'})
MAX_DATE_RANGE_DAYS = 366


@dataclass(frozen=True)
class JobListDateRange:
    """Parsed inclusive date bounds (None = open-ended)."""

    date_from: date | None = None
    date_to: date | None = None
    date_field: JobListDateField = 'updated'


def parse_date_field_param(request) -> JobListDateField:
    params = getattr(request, 'query_params', None) or {}
    raw = (params.get('date_field') or 'updated').strip().lower()
    if raw in VALID_DATE_FIELDS:
        return raw  # type: ignore[return-value]
    return 'updated'


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def parse_job_list_date_range(
    *,
    date_from: str | None,
    date_to: str | None,
    date_field: JobListDateField = 'updated',
) -> JobListDateRange:
    """
    Parse ``date_from`` / ``date_to`` (YYYY-MM-DD).

    Swaps inverted ranges; caps span to ``MAX_DATE_RANGE_DAYS``.
    """
    start = _parse_iso_date(date_from)
    end = _parse_iso_date(date_to)
    if start and end and start > end:
        start, end = end, start
    if start and end:
        span = (end - start).days
        if span > MAX_DATE_RANGE_DAYS:
            end = start + timedelta(days=MAX_DATE_RANGE_DAYS)
    return JobListDateRange(date_from=start, date_to=end, date_field=date_field)


def _aware_start(d: date) -> datetime:
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(d, time.min), tz)


def _aware_end_exclusive(d: date) -> datetime:
    """Start of day after ``d`` for ``__lt`` upper bound (index-friendly)."""
    return _aware_start(d + timedelta(days=1))


def apply_job_date_filters(
    queryset: QuerySet,
    *,
    entity_type: str,
    date_range: JobListDateRange,
) -> QuerySet:
    """
    Apply date filters on indexed columns.

    - ``updated``: ``updated_at`` range (default list freshness).
    - ``operational``: ``shipment_date`` / ``movement_date``.
    """
    if not date_range.date_from and not date_range.date_to:
        return queryset

    if date_range.date_field == 'operational':
        field = 'shipment_date' if entity_type == 'shipment' else 'movement_date'
        qs = queryset
        if date_range.date_from:
            qs = qs.filter(**{f'{field}__gte': date_range.date_from})
        if date_range.date_to:
            qs = qs.filter(**{f'{field}__lte': date_range.date_to})
        return qs

    qs = queryset
    if date_range.date_from:
        qs = qs.filter(updated_at__gte=_aware_start(date_range.date_from))
    if date_range.date_to:
        qs = qs.filter(updated_at__lt=_aware_end_exclusive(date_range.date_to))
    return qs


def date_range_filter_q(
    *,
    entity_type: str,
    date_range: JobListDateRange,
) -> Q:
    """Build a ``Q`` object for date filters (used in tests / explain)."""
    clauses: list[Q] = []
    if date_range.date_field == 'operational':
        field = 'shipment_date' if entity_type == 'shipment' else 'movement_date'
        if date_range.date_from:
            clauses.append(Q(**{f'{field}__gte': date_range.date_from}))
        if date_range.date_to:
            clauses.append(Q(**{f'{field}__lte': date_range.date_to}))
    else:
        if date_range.date_from:
            clauses.append(Q(updated_at__gte=_aware_start(date_range.date_from)))
        if date_range.date_to:
            clauses.append(Q(updated_at__lt=_aware_end_exclusive(date_range.date_to)))
    if not clauses:
        return Q()
    combined = clauses[0]
    for clause in clauses[1:]:
        combined &= clause
    return combined
