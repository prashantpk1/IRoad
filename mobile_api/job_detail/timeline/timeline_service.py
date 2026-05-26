"""
mobile_api/job_detail/timeline/timeline_service.py

Unified timeline engine for explicit shipment / empty-move jobs.

Uses ``iroad_tenants.services.timeline_query`` + cursor keyset pagination.
Reuses ``JobDetailProjectionCache`` for embedded preview (no duplicate ORM scan).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from mobile_api.job_detail.constants import (
    JOB_DETAIL_TIMELINE_PAGE_DEFAULT,
    JOB_DETAIL_TIMELINE_PAGE_MAX,
    JOB_DETAIL_TIMELINE_PREVIEW_LIMIT,
)
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.guards.ownership import driver_pk
from mobile_api.job_detail.services.job_detail_projection_cache import (
    get_projection_cache,
)
from mobile_api.job_detail.timeline.timeline_cursor_service import (
    JobDetailTimelineCursorService,
)
from mobile_api.job_detail.timeline.timeline_event_mapper import (
    dedupe_timeline_events,
    map_logs_to_timeline_events,
    sort_logs_newest_first,
)
from iroad_tenants.services.timeline_service import TimelineService

JobType = Literal['shipment', 'movement']


@dataclass
class TimelinePageResult:
    """Paginated timeline page."""

    timeline_preview: list[dict[str, Any]]
    timeline_cursor: str
    has_more: bool


class JobDetailTimelineService:
    """
    Bounded, cursor-paginated Action Log timelines for Job Detail.

    Preview path reuses ``context.projection_cache`` when present (same scan as
    reconcile/workflow). Pagination uses ``timeline_query`` with limit+1.
    """

    def __init__(
        self,
        *,
        cursor_service: JobDetailTimelineCursorService | None = None,
    ) -> None:
        self._cursor_service = cursor_service or JobDetailTimelineCursorService()

    @classmethod
    def clamp_page_limit(cls, raw_limit: int | None) -> int:
        try:
            value = int(raw_limit) if raw_limit is not None else JOB_DETAIL_TIMELINE_PAGE_DEFAULT
        except (TypeError, ValueError):
            value = JOB_DETAIL_TIMELINE_PAGE_DEFAULT
        return max(1, min(value, JOB_DETAIL_TIMELINE_PAGE_MAX))

    @classmethod
    def clamp_preview_limit(cls, raw_limit: int | None) -> int:
        try:
            value = int(raw_limit) if raw_limit is not None else JOB_DETAIL_TIMELINE_PREVIEW_LIMIT
        except (TypeError, ValueError):
            value = JOB_DETAIL_TIMELINE_PREVIEW_LIMIT
        return max(1, min(value, JOB_DETAIL_TIMELINE_PREVIEW_LIMIT))

    def build_preview_bundle(
        self,
        context: JobDetailContext,
        *,
        request: Any | None = None,
        preview_limit: int | None = None,
    ) -> dict[str, Any]:
        """
        Embedded timeline for Job Detail GET.

        Returns ``timeline_preview``, ``timeline_cursor``, ``has_more``.
        """
        limit = self.clamp_preview_limit(preview_limit)
        if context.job_type == 'shipment' and context.shipment is None:
            return _empty_bundle(limit)
        if context.job_type == 'movement' and context.movement is None:
            return _empty_bundle(limit)

        cache = get_projection_cache(context)
        if cache is not None and cache.primary_logs():
            return self._preview_from_cached_logs(
                cache.primary_logs(),
                limit=limit,
                request=request,
            )

        page = self.fetch_page_for_context(
            context,
            cursor=None,
            limit=limit,
            request=request,
        )
        return {
            'scope': context.job_type,
            'preview_limit': limit,
            'timeline_preview': page.timeline_preview,
            'timeline_cursor': page.timeline_cursor,
            'has_more': page.has_more,
        }

    def fetch_timeline_api_page(
        self,
        context: JobDetailContext,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        request: Any | None = None,
    ) -> dict[str, Any]:
        """
        Dedicated timeline endpoint contract.

        Always uses keyset DB pagination (never reconcile cache) so pages stay
        bounded and independent of Job Detail GET projections.
        """
        page = self.fetch_page_for_context(
            context,
            cursor=cursor,
            limit=limit,
            request=request,
        )
        return {
            'events': page.timeline_preview,
            'next_cursor': page.timeline_cursor,
            'has_more': page.has_more,
        }

    def fetch_page_for_context(
        self,
        context: JobDetailContext,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        request: Any | None = None,
    ) -> TimelinePageResult:
        """Cursor page for explicit job (sub-resource or cache miss)."""
        page_limit = self.clamp_page_limit(limit)
        driver_id = driver_pk(context.driver)

        if context.job_type == 'shipment' and context.shipment is not None:
            return self._fetch_page(
                shipment=context.shipment,
                movement=None,
                driver_id=driver_id,
                cursor=cursor,
                limit=page_limit,
                request=request,
            )
        if context.job_type == 'movement' and context.movement is not None:
            return self._fetch_page(
                shipment=None,
                movement=context.movement,
                driver_id=driver_id,
                cursor=cursor,
                limit=page_limit,
                request=request,
            )
        return TimelinePageResult(timeline_preview=[], timeline_cursor='', has_more=False)

    def _preview_from_cached_logs(
        self,
        logs: list[Any],
        *,
        limit: int,
        request: Any | None,
    ) -> dict[str, Any]:
        """Slice reconcile cache — no additional Action Log query."""
        ordered = sort_logs_newest_first(list(logs))
        window = ordered[: limit + 1]
        has_more = len(window) > limit
        page_logs = window[:limit]
        events = dedupe_timeline_events(
            map_logs_to_timeline_events(page_logs, request=request),
        )
        next_cursor = ''
        if has_more and page_logs:
            next_cursor = self._cursor_service.encode_next_cursor(page_logs[-1])
        return {
            'scope': '',
            'preview_limit': limit,
            'timeline_preview': events,
            'timeline_cursor': next_cursor,
            'has_more': has_more,
        }

    def _fetch_page(
        self,
        *,
        shipment: Any | None,
        movement: Any | None,
        driver_id: Any,
        cursor: str | None,
        limit: int,
        request: Any | None,
    ) -> TimelinePageResult:
        parsed = self._cursor_service.parse_cursor_token(cursor)
        if (cursor or '').strip() and parsed is None:
            return TimelinePageResult(
                timeline_preview=[],
                timeline_cursor='',
                has_more=False,
            )

        fetch_limit = limit + 1
        rows = TimelineService.fetch_scoped_timeline_page(
            shipment=shipment,
            movement=movement,
            driver_id=driver_id,
            cursor=parsed,
            limit=fetch_limit,
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        events = dedupe_timeline_events(
            map_logs_to_timeline_events(page_rows, request=request),
        )
        next_cursor = ''
        if has_more and page_rows:
            next_cursor = self._cursor_service.encode_next_cursor(page_rows[-1])
        return TimelinePageResult(
            timeline_preview=events,
            timeline_cursor=next_cursor,
            has_more=has_more,
        )


def _empty_bundle(preview_limit: int) -> dict[str, Any]:
    return {
        'scope': '',
        'preview_limit': preview_limit,
        'timeline_preview': [],
        'timeline_cursor': '',
        'has_more': False,
    }
