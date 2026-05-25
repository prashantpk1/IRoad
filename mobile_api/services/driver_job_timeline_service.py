"""
Driver job detail timeline feeds — cursor-paginated execution history.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.utils.translation import gettext as _

from iroad_tenants.services.timeline_service import TimelineService
from mobile_api.helpers.timeline_cursor import (
    encode_cursor_from_log,
    parse_timeline_cursor_param,
)
from mobile_api.helpers.job_detail_guards import (
    enforce_detail_payload_size,
    job_detail_timeline_max_items,
)
from mobile_api.helpers.timeline_params import resolve_timeline_page_size
from mobile_api.helpers.timeline_projections import (
    batch_media_previews_by_log,
    project_timeline_item,
)
from mobile_api.services.job_detail_snapshot_service import JobDetailSnapshotService


def _parse_uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _paginate_timeline(
    *,
    driver,
    shipment=None,
    movement=None,
    request=None,
) -> dict[str, Any]:
    driver_id = getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)
    page_size = min(
        resolve_timeline_page_size(request),
        job_detail_timeline_max_items(),
    )
    cursor = parse_timeline_cursor_param(request)
    if request is not None and (getattr(request, 'query_params', None) or {}).get('cursor'):
        if cursor is None:
            return {
                'success': False,
                'code': 'invalid_cursor',
                'error': _('mobile.jobs.timeline.invalid_cursor'),
            }

    rows = TimelineService.fetch_scoped_timeline_page(
        shipment=shipment,
        movement=movement,
        driver_id=driver_id,
        cursor=cursor,
        limit=page_size + 1,
    )
    has_next = len(rows) > page_size
    page_rows = rows[:page_size]
    next_cursor = encode_cursor_from_log(page_rows[-1]) if has_next and page_rows else None

    log_ids = [row.log_id for row in page_rows]
    media_map = batch_media_previews_by_log(log_ids, request=request)

    items = [
        project_timeline_item(
            row,
            request=request,
            media_previews=media_map.get(str(row.log_id), []),
        )
        for row in page_rows
    ]

    job_type = 'shipment' if shipment is not None else 'movement'
    job_id = str(shipment.shipment_id) if shipment else str(movement.movement_id)
    job_no = shipment.shipment_no if shipment else movement.movement_no

    timeline_block = {
        'job_type': job_type,
        'job_id': job_id,
        'job_no': job_no,
        'items': items,
        'pagination': {
            'mode': 'cursor',
            'page_size': page_size,
            'count': len(items),
            'has_next': has_next,
            'next_cursor': next_cursor,
        },
    }
    _payload_size, payload_err = enforce_detail_payload_size(
        {'timeline': timeline_block},
        operation='timeline',
    )
    if payload_err:
        return {
            'success': False,
            'code': 'timeline_payload_too_large',
            'error': _('mobile.jobs.payload_too_large'),
        }

    return {
        'success': True,
        'timeline': timeline_block,
        'meta': {
            'media_batch_count': len(log_ids),
            'item_count': len(items),
        },
    }


class DriverJobTimelineService:
    @classmethod
    def get_shipment_timeline(
        cls,
        *,
        driver,
        shipment_id: str,
        request=None,
    ) -> dict[str, Any]:
        parsed_id = _parse_uuid(shipment_id)
        if not parsed_id:
            return {
                'success': False,
                'code': 'invalid_shipment_id',
                'error': _('mobile.jobs.detail.invalid_id'),
            }

        shipment = JobDetailSnapshotService._load_shipment(
            driver=driver,
            shipment_id=parsed_id,
        )
        if shipment is None:
            return {
                'success': False,
                'code': 'job_not_found',
                'error': _('mobile.jobs.detail.shipment_not_found'),
            }

        return _paginate_timeline(
            driver=driver,
            shipment=shipment,
            request=request,
        )

    @classmethod
    def get_movement_timeline(
        cls,
        *,
        driver,
        movement_id: str,
        request=None,
    ) -> dict[str, Any]:
        parsed_id = _parse_uuid(movement_id)
        if not parsed_id:
            return {
                'success': False,
                'code': 'invalid_movement_id',
                'error': _('mobile.jobs.detail.invalid_id'),
            }

        movement = JobDetailSnapshotService._load_movement(
            driver=driver,
            movement_id=parsed_id,
        )
        if movement is None:
            return {
                'success': False,
                'code': 'job_not_found',
                'error': _('mobile.jobs.detail.movement_not_found'),
            }

        return _paginate_timeline(
            driver=driver,
            movement=movement,
            request=request,
        )
