"""
Driver allowed-actions API — authoritative Action Engine output only.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.utils.translation import gettext as _

from iroad_tenants.services.operation_execution_service import OperationExecutionService
from mobile_api.helpers.execution_workflow_cache import get_allowed_driver_actions_cached
from mobile_api.helpers.job_detail_guards import job_detail_log_scan_limit
from mobile_api.helpers.job_detail_perf import (
    load_scoped_action_logs,
    reconcile_movement_state_from_logs,
    reconcile_shipment_state_from_logs,
)
from mobile_api.services.job_detail_snapshot_service import JobDetailSnapshotService


def _parse_uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (TypeError, ValueError):
        return None


class DriverJobAllowedActionsService:
    @staticmethod
    def _resolve_linkage(*, shipment=None, movement=None):
        booking = None
        booking_item_type = ''
        if shipment is not None:
            if shipment.booking_id:
                booking = shipment.booking
            booking_item_type = (shipment.booking_item_type or '').strip()
        elif movement is not None:
            if movement.booking_id:
                booking = movement.booking
            linked = getattr(movement, 'shipment', None)
            if linked is not None:
                shipment = linked
                if linked.booking_id:
                    booking = linked.booking
                booking_item_type = (linked.booking_item_type or '').strip()
        return booking, shipment, movement, booking_item_type

    @classmethod
    def get_shipment_allowed_actions(
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

        from mobile_api.services.driver_dashboard_current_job import fetch_active_movement

        movement = fetch_active_movement(driver=driver, shipment=shipment)
        booking, shipment, movement, booking_item_type = cls._resolve_linkage(
            shipment=shipment,
            movement=movement,
        )

        log_rows = load_scoped_action_logs(
            shipment=shipment,
            movement=movement,
            driver_id=driver.pk,
            limit=job_detail_log_scan_limit(),
        )
        execution_state = reconcile_shipment_state_from_logs(
            shipment,
            movement=movement,
            driver_id=driver.pk,
            log_rows=log_rows,
            request=request,
        )
        payload = get_allowed_driver_actions_cached(
            request,
            driver=driver,
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
            job_type='shipment',
            job_id=str(shipment.shipment_id),
            job_no=shipment.shipment_no,
        )
        payload['execution_state'] = execution_state

        return {'success': True, 'allowed_actions': payload}

    @classmethod
    def get_movement_allowed_actions(
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

        shipment = getattr(movement, 'shipment', None)
        booking, shipment, movement, booking_item_type = cls._resolve_linkage(
            shipment=shipment,
            movement=movement,
        )

        log_rows = load_scoped_action_logs(
            shipment=shipment,
            movement=movement,
            driver_id=driver.pk,
            limit=job_detail_log_scan_limit(),
        )
        execution_state = (
            reconcile_shipment_state_from_logs(
                shipment,
                movement=movement,
                driver_id=driver.pk,
                log_rows=log_rows,
                request=request,
            )
            if shipment is not None
            else reconcile_movement_state_from_logs(
                movement,
                driver_id=driver.pk,
                log_rows=log_rows,
                request=request,
            )
        )
        payload = get_allowed_driver_actions_cached(
            request,
            driver=driver,
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
            job_type='movement',
            job_id=str(movement.movement_id),
            job_no=movement.movement_no,
        )
        payload['execution_state'] = execution_state

        return {'success': True, 'allowed_actions': payload}
