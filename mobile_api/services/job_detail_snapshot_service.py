"""
Mobile Job Detail orchestration — composes tenant execution services with driver scope.

Does not duplicate workflow rules; delegates to ``iroad_tenants.services``.
"""

from __future__ import annotations

from typing import Any, Literal

from iroad_tenants.services.action_execution_service import ActionExecutionService
from iroad_tenants.services.latest_state_service import LatestStateService
from iroad_tenants.services.operation_execution_service import OperationExecutionService
from iroad_tenants.services.timeline_service import TimelineService
from mobile_api.helpers.dashboard_route import build_shipment_route_summary
from mobile_api.helpers.dashboard_security import (
    assert_movement_row_owned,
    assert_shipment_row_owned,
    movement_queryset_for_driver,
    shipment_queryset_for_driver,
)
from mobile_api.helpers.job_detail_perf import (
    build_timeline_preview_items,
    latest_log_from_rows,
    load_scoped_action_logs,
    reconcile_movement_state_from_logs,
    reconcile_shipment_state_from_logs,
    resolve_log_fetch_limit,
)
from mobile_api.services.driver_dashboard_current_job import (
    fetch_active_movement,
    fetch_latest_action_log,
    project_cod_state,
    project_latest_action_summary,
    project_movement_summary,
    project_pod_state,
    project_shipment_summary,
    project_status_summary,
    project_truck_summary,
)
from tenant_workspace.models import TenantOperationActionLog

JobEntityType = Literal['shipment', 'movement']


class JobDetailSnapshotService:
    """Bounded job-detail read model for driver execution screens."""

    @classmethod
    def timeline_preview_limit(cls) -> int:
        from mobile_api.helpers.job_detail_params import job_detail_timeline_preview_limit

        return job_detail_timeline_preview_limit()

    @classmethod
    def _load_shipment(cls, *, driver, shipment_id: str):
        row = (
            shipment_queryset_for_driver(driver)
            .select_related(
                'truck',
                'booking',
                'loading_address',
                'delivery_address',
            )
            .filter(pk=shipment_id)
            .first()
        )
        if row is None or not assert_shipment_row_owned(driver, row):
            return None
        return row

    @classmethod
    def _load_movement(cls, *, driver, movement_id: str):
        row = (
            movement_queryset_for_driver(driver)
            .select_related(
                'shipment',
                'shipment__loading_address',
                'shipment__delivery_address',
                'truck',
                'from_location_point',
                'to_location_point',
            )
            .filter(pk=movement_id)
            .first()
        )
        if row is None or not assert_movement_row_owned(driver, row):
            return None
        return row

    @classmethod
    def get_allowed_driver_actions(
        cls,
        *,
        driver,
        shipment=None,
        movement=None,
        booking_item_type: str = '',
        request=None,
    ) -> dict[str, Any]:
        booking = None
        if shipment is not None and shipment.booking_id:
            booking = shipment.booking
        elif movement is not None and movement.booking_id:
            booking = movement.booking
        if shipment is not None and not booking_item_type:
            booking_item_type = (shipment.booking_item_type or '').strip()
        job_type = 'shipment' if shipment is not None else 'movement'
        job_id = ''
        job_no = ''
        if shipment is not None:
            job_id = str(shipment.shipment_id)
            job_no = shipment.shipment_no
        elif movement is not None:
            job_id = str(movement.movement_id)
            job_no = movement.movement_no
        return OperationExecutionService.get_allowed_driver_actions(
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
            request=request,
            job_type=job_type,
            job_id=job_id,
            job_no=job_no,
        )

    @classmethod
    def build_execution_timeline(
        cls,
        *,
        driver,
        shipment=None,
        movement=None,
        limit: int | None = None,
        request=None,
    ) -> list[dict[str, Any]]:
        driver_id = getattr(driver, 'pk', None)
        return TimelineService.build_execution_timeline(
            shipment=shipment,
            movement=movement,
            driver_id=driver_id,
            limit=limit,
            request=request,
        )

    @classmethod
    def derive_latest_execution_state(
        cls,
        *,
        shipment,
        movement=None,
        driver=None,
        request=None,
    ) -> dict[str, Any]:
        driver_id = getattr(driver, 'pk', None) if driver else None
        return LatestStateService.derive_latest_execution_state(
            shipment,
            movement=movement,
            driver_id=driver_id,
            request=request,
        )

    @classmethod
    def get_job_detail_snapshot(
        cls,
        *,
        driver,
        job_type: JobEntityType,
        job_id: str,
        request=None,
        include_timeline_preview: bool = True,
        include_allowed_actions: bool = True,
        preloaded_shipment=None,
        preloaded_movement=None,
    ) -> dict[str, Any] | None:
        """
        Single read orchestration for Job Detail screen (no portal serializers).
        """
        if job_type == 'shipment':
            shipment = preloaded_shipment or cls._load_shipment(
                driver=driver,
                shipment_id=job_id,
            )
            if shipment is None:
                return None
            movement = fetch_active_movement(driver=driver, shipment=shipment)
            if movement is not None and not assert_movement_row_owned(driver, movement):
                movement = None

            driver_id = getattr(driver, 'pk', None)
            need_logs = include_timeline_preview or True
            log_limit = resolve_log_fetch_limit(
                include_timeline_preview=include_timeline_preview,
                include_execution_state=True,
                preview_limit=cls.timeline_preview_limit(),
            )
            log_rows = (
                load_scoped_action_logs(
                    shipment=shipment,
                    movement=movement,
                    driver_id=driver_id,
                    limit=log_limit,
                )
                if need_logs
                else []
            )
            latest_log = latest_log_from_rows(log_rows) or fetch_latest_action_log(
                driver=driver,
                shipment=shipment,
            )
            allowed = (
                cls.get_allowed_driver_actions(
                    driver=driver,
                    shipment=shipment,
                    movement=movement,
                    request=request,
                )
                if include_allowed_actions
                else None
            )
            timeline = (
                build_timeline_preview_items(
                    log_rows,
                    request=request,
                    preview_limit=cls.timeline_preview_limit(),
                )
                if include_timeline_preview
                else []
            )
            execution_state = reconcile_shipment_state_from_logs(
                shipment,
                movement=movement,
                driver_id=driver_id,
                log_rows=log_rows,
                request=request,
            )
            route_block = build_shipment_route_summary(shipment, request)
            return {
                'job_type': 'shipment',
                'job_id': str(shipment.shipment_id),
                'job_no': shipment.shipment_no,
                'shipment': project_shipment_summary(shipment=shipment),
                'movement': project_movement_summary(movement),
                'status': project_status_summary(shipment=shipment, movement=movement),
                'execution_state': execution_state,
                'route': route_block,
                'truck': project_truck_summary(shipment.truck),
                'latest_action': project_latest_action_summary(latest_log, request),
                'pod': project_pod_state(shipment=shipment),
                'cod': project_cod_state(shipment=shipment),
                'allowed_actions': allowed,
                'timeline_preview': timeline,
            }

        movement = preloaded_movement or cls._load_movement(
            driver=driver,
            movement_id=job_id,
        )
        if movement is None:
            return None
        shipment = getattr(movement, 'shipment', None)
        if shipment is not None and not assert_shipment_row_owned(driver, shipment):
            shipment = None
        driver_id = getattr(driver, 'pk', None)
        log_limit = resolve_log_fetch_limit(
            include_timeline_preview=include_timeline_preview,
            include_execution_state=True,
            preview_limit=cls.timeline_preview_limit(),
        )
        log_rows = load_scoped_action_logs(
            shipment=shipment,
            movement=movement,
            driver_id=driver_id,
            limit=log_limit,
        )
        latest_log = latest_log_from_rows(log_rows)
        if latest_log is None and shipment is not None:
            latest_log = fetch_latest_action_log(driver=driver, shipment=shipment)
        elif latest_log is None:
            latest_log = (
                TenantOperationActionLog.objects.filter(
                    truck_movement_id=movement.pk,
                    driver_id=driver.pk,
                )
                .select_related('operation_action')
                .order_by('-log_date', '-created_at')
                .first()
            )
        allowed = (
            cls.get_allowed_driver_actions(
                driver=driver,
                shipment=shipment,
                movement=movement,
                request=request,
            )
            if include_allowed_actions
            else None
        )
        timeline = (
            build_timeline_preview_items(
                log_rows,
                request=request,
                preview_limit=cls.timeline_preview_limit(),
            )
            if include_timeline_preview
            else []
        )
        route_block = (
            build_shipment_route_summary(shipment, request)
            if shipment is not None
            else {'summary': '', 'from_label': '', 'to_label': ''}
        )
        return {
            'job_type': 'movement',
            'job_id': str(movement.movement_id),
            'job_no': movement.movement_no,
            'shipment': project_shipment_summary(shipment=shipment) if shipment else None,
            'movement': project_movement_summary(movement),
            'status': project_status_summary(
                shipment=shipment,
                movement=movement,
            )
            if shipment
            else {
                'shipment_status': None,
                'movement_status': movement.status,
                'operational_stage': movement.status,
                'has_active_movement': True,
            },
            'execution_state': (
                reconcile_shipment_state_from_logs(
                    shipment,
                    movement=movement,
                    driver_id=driver_id,
                    log_rows=log_rows,
                    request=request,
                )
                if shipment
                else reconcile_movement_state_from_logs(
                    movement,
                    driver_id=driver_id,
                    log_rows=log_rows,
                    request=request,
                )
            ),
            'route': route_block,
            'truck': project_truck_summary(movement.truck),
            'latest_action': project_latest_action_summary(latest_log, request),
            'pod': project_pod_state(shipment=shipment) if shipment else None,
            'cod': project_cod_state(shipment=shipment) if shipment else None,
            'allowed_actions': allowed,
            'timeline_preview': timeline,
        }

    execute_driver_action = ActionExecutionService.execute_driver_action
    validate_driver_action_execution = ActionExecutionService.validate_driver_action_execution
    apply_execution_side_effects = ActionExecutionService.apply_execution_side_effects
