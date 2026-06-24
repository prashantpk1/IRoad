"""
mobile_api/job_detail/projections/timeline_projection.py

``timeline`` section — bounded preview for Job Detail main payload.

Full pages use ``JobDetailTimelineService.fetch_page_for_context`` (cursor).
"""
from __future__ import annotations

from typing import Any

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.timeline.timeline_event_mapper import sort_timeline_display_order
from mobile_api.job_detail.timeline.timeline_service import JobDetailTimelineService

_EMPTY_TIMELINE: dict[str, Any] = {
    'scope': '',
    'preview_limit': 0,
    'timeline_preview': [],
    'timeline_cursor': '',
    'has_more': False,
}


def build_timeline_section(
    context: JobDetailContext,
    *,
    request: Any | None = None,
    preview_limit: int | None = None,
) -> dict[str, Any]:
    """
    Action-Log-authoritative timeline preview (reuses projection cache when loaded).

    Contract::

        timeline_preview: list[events]
        timeline_cursor: str   # next page token when has_more
        has_more: bool
    """
    if context.job_type == 'shipment' and context.shipment is None:
        return dict(_EMPTY_TIMELINE)
    if context.job_type == 'movement' and context.movement is None:
        return dict(_EMPTY_TIMELINE)
    if context.job_type == 'booking' and context.booking is None:
        return dict(_EMPTY_TIMELINE)

    bundle = JobDetailTimelineService().build_preview_bundle(
        context,
        request=request,
        preview_limit=preview_limit,
    )
    bundle['scope'] = context.job_type
    bundle['timeline_preview'] = sort_timeline_display_order(
        list(bundle.get('timeline_preview') or []),
    )
    # Operational issues are surfaced via alerts / operational_issues blocks only.
    # They are intentionally excluded from the action-log timeline preview.
    bundle['includes_operational_issues'] = False
    return bundle
