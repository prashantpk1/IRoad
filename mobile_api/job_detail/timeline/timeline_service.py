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
    merge_actions_with_timeline_logs,
    map_logs_to_timeline_events,
    sort_logs_newest_first,
)
from iroad_tenants.services.timeline_service import TimelineService
from iroad_tenants.operation_runtime.impacts import operation_action_matches
from tenant_workspace.models import TenantOperationAction

JobType = Literal['shipment', 'movement']

AUTO_ACTION_CHANNELS = frozenset({'auto_cod_verify'})
AUTO_ACTION_CODES = frozenset({'A_POD_VERIFY'})


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
        if cache is not None:
            cached_logs = cache.primary_logs()
            workflow_events = self._workflow_events_for_context(
                context,
                logs=cached_logs,
                request=request,
            )
            if workflow_events:
                return self._bundle_from_workflow_events(
                    workflow_events,
                    limit=limit,
                    scope=context.job_type,
                )
            if cached_logs:
                return self._preview_from_cached_logs(
                    cached_logs,
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
            workflow_page = self._fetch_workflow_page(
                context,
                shipment=context.shipment,
                movement=None,
                driver_id=driver_id,
                limit=page_limit,
                request=request,
            )
            if workflow_page.timeline_preview:
                return workflow_page
            return self._fetch_page(
                shipment=context.shipment,
                movement=None,
                driver_id=driver_id,
                cursor=cursor,
                limit=page_limit,
                request=request,
            )
        if context.job_type == 'movement' and context.movement is not None:
            workflow_page = self._fetch_workflow_page(
                context,
                shipment=None,
                movement=context.movement,
                driver_id=driver_id,
                limit=page_limit,
                request=request,
            )
            if workflow_page.timeline_preview:
                return workflow_page
            return self._fetch_page(
                shipment=None,
                movement=context.movement,
                driver_id=driver_id,
                cursor=cursor,
                limit=page_limit,
                request=request,
            )
        return TimelinePageResult(timeline_preview=[], timeline_cursor='', has_more=False)

    def _workflow_actions(self) -> list[Any]:
        qs = TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
            action_scope__in=('job', 'without', ''),
            mobile_visible=True,
            admin_only=False,
        ).order_by('sequence_number', 'action_code')
        try:
            return list(qs)
        except Exception as exc:
            if exc.__class__.__name__ == 'DatabaseOperationForbidden':
                return []
            raise

    def _filter_workflow_actions_for_context(
        self,
        actions: list[Any],
        *,
        context: JobDetailContext,
    ) -> list[Any]:
        """
        Keep only workflow actions applicable to this job type/context.

        - Shipment timelines do not show booking-start action (A1).
        - Credit shipments do not show COD collection action (A9).
        """
        if not actions:
            return []

        if context.job_type == 'movement':
            filtered: list[Any] = []
            for action in actions:
                cat = (getattr(action, 'sequence_category', '') or '').strip().lower()
                code = (getattr(action, 'action_code', '') or '').strip().upper()
                if cat == 'empty_move' or code.startswith('EM'):
                    filtered.append(action)
            return filtered

        if context.job_type == 'shipment':
            is_cod = False
            if context.shipment is not None:
                is_cod = (getattr(context.shipment, 'order_type', '') or '').strip().upper() == 'COD'
            filtered: list[Any] = []
            for action in actions:
                cat = (getattr(action, 'sequence_category', '') or '').strip().lower()
                code = (getattr(action, 'action_code', '') or '').strip().upper()
                if cat == 'empty_move' or code.startswith('EM'):
                    continue
                if operation_action_matches(action, 'start job', 'a1', 'action 1'):
                    continue
                if (not is_cod) and operation_action_matches(
                    action,
                    'collect payment',
                    'a9',
                    'action 9',
                    'cod',
                ):
                    continue
                filtered.append(action)
            return filtered

        if context.job_type != 'shipment' or context.shipment is None:
            return list(actions)

        is_cod = (getattr(context.shipment, 'order_type', '') or '').strip().upper() == 'COD'
        filtered: list[Any] = []
        for action in actions:
            if operation_action_matches(action, 'start job', 'a1', 'action 1'):
                continue
            if (not is_cod) and operation_action_matches(
                action,
                'collect payment',
                'a9',
                'action 9',
                'cod',
            ):
                continue
            filtered.append(action)
        return filtered

    def _append_system_auto_events(
        self,
        events: list[dict[str, Any]],
        logs: list[Any],
        *,
        request: Any | None = None,
    ) -> list[dict[str, Any]]:
        _ = request
        existing_log_ids = {
            str(e.get('log_id') or '').strip()
            for e in events
            if e.get('log_id')
        }
        out = list(events)
        for log in sorted(logs, key=lambda row: getattr(row, 'log_date', None) or ''):
            action = getattr(log, 'operation_action', None)
            if action is None:
                continue
            code = (getattr(action, 'action_code', '') or '').strip()
            channel = (getattr(log, 'source_channel', '') or '').strip()
            if code not in AUTO_ACTION_CODES and channel not in AUTO_ACTION_CHANNELS:
                continue
            log_id = str(getattr(log, 'log_id', None) or getattr(log, 'pk', '') or '')
            if not log_id or log_id in existing_log_ids:
                continue
            log_date = getattr(log, 'log_date', None)
            out.append(
                {
                    'log_id': log_id,
                    'log_no': str(getattr(log, 'log_no', '') or ''),
                    'log_date': log_date.isoformat() if hasattr(log_date, 'isoformat') else '',
                    'action_code': code,
                    'action_label': (
                        getattr(action, 'english_label', None) or code
                    ),
                    'timeline_state': 'performed',
                    'sequence_number': 999,
                    'source': str(getattr(log, 'source', '') or '') or 'System',
                    'source_channel': channel,
                    'status_impact': (getattr(action, 'shipment_status_impact', '') or '').strip()
                    or None,
                    'is_system_auto': True,
                    'is_performed': True,
                    'authority': 'action_log',
                    'append_only': True,
                },
            )
            existing_log_ids.add(log_id)
        return out

    def _workflow_events_for_context(
        self,
        context: JobDetailContext,
        *,
        logs: list[Any],
        request: Any | None,
    ) -> list[dict[str, Any]]:
        actions = self._workflow_actions()
        if not actions:
            return []
        actions = self._filter_workflow_actions_for_context(actions, context=context)
        if not actions:
            return []
        events = merge_actions_with_timeline_logs(actions, logs, request=request)
        return self._append_system_auto_events(events, logs, request=request)

    def _bundle_from_workflow_events(
        self,
        events: list[dict[str, Any]],
        *,
        limit: int,
        scope: str,
    ) -> dict[str, Any]:
        window = events[:limit]
        return {
            'scope': scope,
            'preview_limit': limit,
            'timeline_preview': window,
            'timeline_cursor': '',
            'has_more': len(events) > limit,
        }

    def _fetch_workflow_page(
        self,
        context: JobDetailContext,
        *,
        shipment: Any | None,
        movement: Any | None,
        driver_id: Any,
        limit: int,
        request: Any | None,
    ) -> TimelinePageResult:
        actions = self._workflow_actions()
        if not actions:
            return TimelinePageResult(
                timeline_preview=[],
                timeline_cursor='',
                has_more=False,
            )
        actions = self._filter_workflow_actions_for_context(actions, context=context)
        if not actions:
            return TimelinePageResult(
                timeline_preview=[],
                timeline_cursor='',
                has_more=False,
            )

        logs = TimelineService.fetch_scoped_timeline_page(
            shipment=shipment,
            movement=movement,
            driver_id=driver_id,
            cursor=None,
            limit=max(len(actions) * 3, limit + 1),
        )
        events = self._workflow_events_for_context(
            context,
            logs=logs,
            request=request,
        )
        return TimelinePageResult(
            timeline_preview=events[:limit],
            timeline_cursor='',
            has_more=len(events) > limit,
        )

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
