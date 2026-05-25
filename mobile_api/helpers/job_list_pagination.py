"""
mobile_api/helpers/job_list_pagination.py

Job-list pagination — keyset (cursor) default, bounded offset fallback, optional COUNT.
"""
from __future__ import annotations

import math

from rest_framework.response import Response

from mobile_api.helpers.job_list_cursor import (
    apply_cursor_filter,
    encode_cursor_from_row,
    parse_cursor_param,
    resolve_pagination_mode,
)
from mobile_api.helpers.job_list_guards import (
    clamp_page_size,
    reject_offset_pagination,
    validate_pagination_request,
)
from mobile_api.helpers.job_list_observability import job_list_timer
from mobile_api.helpers.job_list_cache import (
    get_cached_list_total,
    set_cached_list_total,
)
from mobile_api.helpers.job_list_performance import resolve_include_total
from mobile_api.pagination import MobileApiPagination
from mobile_api.response_envelope import build_meta


class MobileJobListPagination(MobileApiPagination):
    """
    Paginator for driver job list feeds.

    - Default: **cursor** keyset pagination (``cursor`` query param).
    - Fallback: **offset** when ``page`` is sent (legacy).
    - ``include_total=1`` only runs COUNT (cached when possible).
    """

    pagination_error: str | None = None
    pagination_mode: str = 'cursor'
    next_cursor: str | None = None
    has_more: bool = False

    def get_page_size(self, request):
        from django.conf import settings as django_settings

        params = getattr(request, 'query_params', None) or {}
        raw = params.get(self.page_size_query_param)
        if raw is None:
            raw = getattr(django_settings, 'MOBILE_API_DEFAULT_PAGE_SIZE', 10)
        return clamp_page_size(raw)

    def get_page_number(self, request, page_size):
        try:
            return max(1, int(super().get_page_number(request, page_size)))
        except (TypeError, ValueError):
            return 1

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        self.pagination_error = None
        self.next_cursor = None
        self.has_more = False
        self.include_total = resolve_include_total(request)
        page_size = self.get_page_size(request)
        entity_type = getattr(view, 'job_list_entity_type', '') if view else ''
        sort = getattr(view, 'job_list_sort', 'updated_desc') if view else 'updated_desc'
        self.pagination_mode = resolve_pagination_mode(request)
        offset_err = reject_offset_pagination(request)
        if offset_err and (getattr(request, 'query_params', None) or {}).get('page'):
            self.pagination_error = offset_err
            return None

        if self.pagination_mode == 'cursor':
            return self._paginate_cursor(
                queryset,
                request,
                page_size=page_size,
                entity_type=entity_type,
                sort=sort,
            )
        return self._paginate_offset(
            queryset,
            request,
            page_size=page_size,
            entity_type=entity_type,
        )

    def _paginate_cursor(
        self,
        queryset,
        request,
        *,
        page_size: int,
        entity_type: str,
        sort: str,
    ):
        cursor = parse_cursor_param(request, entity_type=entity_type)
        if cursor is not None and cursor.sort != sort:
            self.pagination_error = 'Cursor sort mismatch; restart from first page.'
            return None

        qs = queryset
        if cursor is not None:
            qs = apply_cursor_filter(
                qs,
                entity_type=entity_type,
                sort=sort,
                cursor=cursor,
            )

        with job_list_timer(operation='paginate_cursor', entity_type=entity_type) as metrics:
            metrics['page_size'] = page_size
            metrics['include_total'] = self.include_total
            metrics['pagination_mode'] = 'cursor'
            fetch_size = page_size + 1
            page_rows = list(qs[:fetch_size])
            self.has_more = len(page_rows) > page_size
            if self.has_more:
                page_rows = page_rows[:page_size]
            metrics['item_count'] = len(page_rows)

            total_count = None
            if self.include_total:
                total_count = self._resolve_total_count_cached(
                    queryset,
                    request,
                    entity_type=entity_type,
                )

        if page_rows:
            self.next_cursor = encode_cursor_from_row(
                page_rows[-1],
                entity_type=entity_type,
                sort=sort,
            )

        self.page = _JobListPage(
            number=1,
            page_size=page_size,
            object_list=page_rows,
            total_count=total_count,
        )
        self.page_size = page_size
        return page_rows

    def _paginate_offset(
        self,
        queryset,
        request,
        *,
        page_size: int,
        entity_type: str,
    ):
        page_number = self.get_page_number(request, page_size)
        err = validate_pagination_request(page=page_number, page_size=page_size)
        if err:
            self.pagination_error = err
            return None

        with job_list_timer(operation='paginate_offset', entity_type=entity_type) as metrics:
            metrics['page'] = page_number
            metrics['page_size'] = page_size
            metrics['include_total'] = self.include_total
            metrics['pagination_mode'] = 'offset'
            offset = (page_number - 1) * page_size
            page_rows = list(queryset[offset : offset + page_size])
            metrics['item_count'] = len(page_rows)
            total_count = None
            if self.include_total:
                total_count = self._resolve_total_count_cached(
                    queryset,
                    request,
                    entity_type=entity_type,
                )

        self.page = _JobListPage(
            number=page_number,
            page_size=page_size,
            object_list=page_rows,
            total_count=total_count,
        )
        self.page_size = page_size
        return page_rows

    def _resolve_total_count_cached(self, queryset, request, *, entity_type: str) -> int:
        fingerprint = getattr(request, '_job_list_count_fingerprint', '') or ''
        tenant = getattr(request, '_job_list_tenant_schema', '') or ''
        driver_id = getattr(request, '_job_list_driver_id', '') or ''
        if fingerprint and tenant and driver_id:
            cached = get_cached_list_total(
                tenant_schema=tenant,
                driver_id=driver_id,
                fingerprint=fingerprint,
            )
            if cached is not None:
                return cached
        with job_list_timer(operation='count', entity_type=entity_type):
            total = int(queryset.count())
        if fingerprint and tenant and driver_id:
            set_cached_list_total(
                tenant_schema=tenant,
                driver_id=driver_id,
                fingerprint=fingerprint,
                total=total,
            )
        return total

    def get_paginated_response(self, data, message='Data retrieved successfully'):
        page_size = self.get_page_size(self.request)
        total_records = self.page.total_count
        if total_records is None:
            total_pages = None
        else:
            total_pages = (
                math.ceil(total_records / page_size) if page_size else 1
            )

        payload = {
            'items': data,
            'page_size': page_size,
            'pagination_mode': self.pagination_mode,
        }
        if self.pagination_mode == 'cursor':
            payload['next_cursor'] = self.next_cursor
            payload['has_more'] = self.has_more
        else:
            payload['current_page'] = self.page.number
            if total_records is not None:
                payload['total_records'] = total_records
                payload['total_pages'] = total_pages

        if total_records is not None and self.pagination_mode == 'cursor':
            payload['total_records'] = total_records
            payload['total_pages'] = total_pages

        return Response({
            'status': 1,
            'message': str(message),
            'data': payload,
            'meta': build_meta(self.request),
        })


class _JobListPage:
    """Minimal page object compatible with existing view code."""

    def __init__(self, *, number: int, page_size: int, object_list: list, total_count: int | None):
        self.number = number
        self.paginator = _JobListPaginator(count=total_count, per_page=page_size)
        self.object_list = object_list

    def __iter__(self):
        return iter(self.object_list)

    def __len__(self):
        return len(self.object_list)


class _JobListPaginator:
    def __init__(self, *, count: int | None, per_page: int):
        self.count = count
        self.per_page = per_page
