"""
Driver Job Detail read service — bounded queries, flat DTO output.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.utils.translation import gettext as _

from mobile_api.helpers.job_detail_params import (
    job_detail_timeline_preview_limit,
    parse_job_detail_include_flags,
)
from mobile_api.helpers.job_detail_projections import build_job_detail_dto
from mobile_api.services.job_detail_snapshot_service import JobDetailSnapshotService


def _parse_uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (TypeError, ValueError):
        return None


class DriverJobDetailService:
    @staticmethod
    def get_shipment_job_detail(
        *,
        driver,
        tenant_user,
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

        flags = parse_job_detail_include_flags(request) if request is not None else {
            'include_timeline': True,
            'include_actions': True,
        }
        limit = job_detail_timeline_preview_limit()

        shipment_row = JobDetailSnapshotService._load_shipment(
            driver=driver,
            shipment_id=parsed_id,
        )
        if shipment_row is None:
            return {
                'success': False,
                'code': 'job_not_found',
                'error': _('mobile.jobs.detail.shipment_not_found'),
            }

        raw = JobDetailSnapshotService.get_job_detail_snapshot(
            driver=driver,
            job_type='shipment',
            job_id=parsed_id,
            request=request,
            include_timeline_preview=flags['include_timeline'],
            include_allowed_actions=flags['include_actions'],
            preloaded_shipment=shipment_row,
        )
        if raw is None:
            return {
                'success': False,
                'code': 'job_not_found',
                'error': _('mobile.jobs.detail.shipment_not_found'),
            }

        movement_row = None
        from mobile_api.services.driver_dashboard_current_job import fetch_active_movement

        movement_row = fetch_active_movement(driver=driver, shipment=shipment_row)

        dto = build_job_detail_dto(
            raw_snapshot=raw,
            driver=driver,
            tenant_user=tenant_user,
            shipment_row=shipment_row,
            movement_row=movement_row,
            request=request,
        )

        return {
            'success': True,
            'snapshot': dto,
            'meta': {
                'entity_type': 'shipment',
                'include_timeline': flags['include_timeline'],
                'include_actions': flags['include_actions'],
                'timeline_preview_limit': limit,
            },
        }

    @staticmethod
    def get_movement_job_detail(
        *,
        driver,
        tenant_user,
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

        flags = parse_job_detail_include_flags(request) if request is not None else {
            'include_timeline': True,
            'include_actions': True,
        }
        limit = job_detail_timeline_preview_limit()

        movement_row = JobDetailSnapshotService._load_movement(
            driver=driver,
            movement_id=parsed_id,
        )
        if movement_row is None:
            return {
                'success': False,
                'code': 'job_not_found',
                'error': _('mobile.jobs.detail.movement_not_found'),
            }

        shipment_row = getattr(movement_row, 'shipment', None)

        raw = JobDetailSnapshotService.get_job_detail_snapshot(
            driver=driver,
            job_type='movement',
            job_id=parsed_id,
            request=request,
            include_timeline_preview=flags['include_timeline'],
            include_allowed_actions=flags['include_actions'],
            preloaded_movement=movement_row,
            preloaded_shipment=shipment_row,
        )
        if raw is None:
            return {
                'success': False,
                'code': 'job_not_found',
                'error': _('mobile.jobs.detail.movement_not_found'),
            }

        dto = build_job_detail_dto(
            raw_snapshot=raw,
            driver=driver,
            tenant_user=tenant_user,
            shipment_row=shipment_row,
            movement_row=movement_row,
            request=request,
        )

        return {
            'success': True,
            'snapshot': dto,
            'meta': {
                'entity_type': 'movement',
                'include_timeline': flags['include_timeline'],
                'include_actions': flags['include_actions'],
                'timeline_preview_limit': limit,
            },
        }
