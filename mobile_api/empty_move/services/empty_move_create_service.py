"""
Create driver-initiated empty truck movements (On Call mode).

Locations are tenant master UUIDs; mobile GPS (from/to latitude & longitude)
is stored on the TML map-link fields and on the EM1 action log. EM1 always
fires automatically when the empty move is created.
"""
from __future__ import annotations

from typing import Any, Mapping

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
from iroad_tenants.operation_runtime.movement_ops import (
    apply_movement_route_map_links,
    birth_empty_move_for_driver,
)
from iroad_tenants.services.action_execution_service import ActionExecutionService
from mobile_api.dashboard.selectors.dashboard_booking_selector import (
    DashboardBookingSelector,
)
from mobile_api.dashboard.selectors.dashboard_movement_selector import (
    DashboardMovementSelector,
)
from mobile_api.empty_move.exceptions import EmptyMoveError
from mobile_api.helpers.mobile_execution_guard import (
    MobileExecutionContext,
    mobile_execution_guard,
)
from mobile_api.job_detail.guards.ownership import driver_pk
from mobile_api.job_detail.projections.job_location_projection import (
    serialize_location_point,
)
from tenant_workspace.models import (
    DriverMaster,
    TenantLocationMaster,
    TenantOperationAction,
    TenantTruckMovementLog,
    TruckDriverAssignmentHistory,
    TruckMaster,
)


def _driver_label(driver: Any) -> str:
    code = str(getattr(driver, 'driver_code', '') or '').strip()
    name = str(getattr(driver, 'english_name', '') or '').strip()
    if code and name:
        return f'{code} - {name}'[:200]
    return (code or name or 'driver')[:200]


def _resolve_driver_truck(driver: Any, truck_id: Any | None) -> TruckMaster | None:
    if truck_id:
        truck = TruckMaster.objects.filter(pk=truck_id).first()
        if truck is None:
            raise EmptyMoveError(
                str(_('mobile.empty_move.truck_not_found')),
                code='truck_not_found',
                http_status=404,
                message_key='mobile.empty_move.truck_not_found',
            )
        return truck

    assignment = (
        TruckDriverAssignmentHistory.objects.filter(
            driver=driver,
            assigned_to__isnull=True,
        )
        .select_related('truck')
        .order_by('-assigned_from', '-created_at')
        .first()
    )
    if assignment and assignment.truck_id:
        return assignment.truck

    driver_pk_val = driver_pk(driver)
    if driver_pk_val is not None:
        truck = TruckMaster.objects.filter(default_driver_id=driver_pk_val).first()
        if truck is not None:
            return truck
    return None


def _resolve_location(location_id) -> TenantLocationMaster:
    location = TenantLocationMaster.active_serviceable_objects.filter(
        location_id=location_id,
    ).first()
    if location is None:
        raise EmptyMoveError(
            str(_('mobile.empty_move.location_not_found')),
            code='location_not_found',
            http_status=404,
            message_key='mobile.empty_move.location_not_found',
        )
    return location


def _assert_on_call_state(driver: Any, *, tenant_schema: str) -> None:
    booking_sel = DashboardBookingSelector().select_current_driver_booking(
        driver,
        tenant_schema=tenant_schema,
    )
    if booking_sel is not None:
        raise EmptyMoveError(
            str(_('mobile.empty_move.active_job_blocks_empty_move')),
            code='active_job_present',
            http_status=409,
            message_key='mobile.empty_move.active_job_blocks_empty_move',
        )

    existing = DashboardMovementSelector().select_current_empty_move(
        driver,
        tenant_schema=tenant_schema,
    )
    if existing is not None:
        raise EmptyMoveError(
            str(_('mobile.empty_move.already_active')),
            code='empty_move_already_active',
            http_status=409,
            message_key='mobile.empty_move.already_active',
        )


def _coord_str(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()[:32]


def _resolve_start_gps(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Prefer explicit from_* coords; fall back to legacy latitude/longitude."""
    from_lat = _coord_str(payload.get('from_latitude'))
    from_lng = _coord_str(payload.get('from_longitude'))
    if from_lat and from_lng:
        return from_lat, from_lng
    return _coord_str(payload.get('latitude')), _coord_str(payload.get('longitude'))


def _project_movement_response(
    movement: Any,
    *,
    request: Any | None = None,
    workflow_started: bool = False,
) -> dict[str, Any]:
    movement_id = getattr(movement, 'movement_id', None) or getattr(movement, 'pk', None)
    return {
        'job_type': 'movement',
        'job_id': str(movement_id or ''),
        'job_no': str(getattr(movement, 'movement_no', '') or ''),
        'movement_id': str(movement_id or ''),
        'movement_no': str(getattr(movement, 'movement_no', '') or ''),
        'movement_status': str(getattr(movement, 'status', '') or ''),
        'empty_move_reason': str(getattr(movement, 'empty_move_reason', '') or ''),
        'from_location': serialize_location_point(
            getattr(movement, 'from_location_point', None),
            request=request,
        ),
        'to_location': serialize_location_point(
            getattr(movement, 'to_location_point', None),
            request=request,
        ),
        'workflow_started': workflow_started,
    }


class EmptyMoveCreateService:
    """Create empty move rows and always fire EM1 (Start Movement)."""

    def create_empty_move(
        self,
        *,
        driver: Any,
        tenant_user: Any,
        tenant_schema: str,
        payload: Mapping[str, Any],
        request: Any | None = None,
        jwt_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        schema = (tenant_schema or '').strip()
        if not schema:
            raise EmptyMoveError(
                str(_('mobile.auth.tenant_required')),
                code='tenant_required',
                http_status=400,
                message_key='mobile.auth.tenant_required',
            )

        if str(getattr(driver, 'driver_status', '') or '').strip() != DriverMaster.Status.ACTIVE:
            raise EmptyMoveError(
                str(_('mobile.auth.driver_inactive')),
                code='driver_inactive',
                http_status=403,
                message_key='mobile.auth.driver_inactive',
            )

        notes = str(payload.get('notes') or '').strip()
        client_action_id = str(payload.get('client_action_id') or '').strip()

        with schema_context(schema):
            _assert_on_call_state(driver, tenant_schema=schema)

            truck = _resolve_driver_truck(driver, payload.get('truck_id'))
            if truck is None:
                raise EmptyMoveError(
                    str(_('mobile.empty_move.truck_required')),
                    code='truck_required',
                    http_status=400,
                    message_key='mobile.empty_move.truck_required',
                )

            from_location = _resolve_location(payload['from_location_id'])
            to_location = _resolve_location(payload['to_location_id'])

            movement_date = payload.get('movement_date') or timezone.localdate()
            created_by = _driver_label(driver)

            start_lat, start_lng = _resolve_start_gps(payload)

            with transaction.atomic():
                movement = birth_empty_move_for_driver(
                    driver=driver,
                    truck=truck,
                    from_location=from_location,
                    to_location=to_location,
                    empty_move_reason=str(payload['empty_move_reason']),
                    movement_date=movement_date,
                    notes=notes,
                    created_by_label=created_by,
                )
                apply_movement_route_map_links(
                    movement,
                    from_latitude=start_lat,
                    from_longitude=start_lng,
                    to_latitude=_coord_str(payload.get('to_latitude')),
                    to_longitude=_coord_str(payload.get('to_longitude')),
                )

                workflow_started = self._auto_start_movement(
                    movement=movement,
                    driver=driver,
                    tenant_user=tenant_user,
                    truck=truck,
                    tenant_schema=schema,
                    jwt_payload=jwt_payload or {},
                    notes=notes,
                    client_action_id=client_action_id,
                    latitude=start_lat or None,
                    longitude=start_lng or None,
                )
                movement.refresh_from_db()

                movement = (
                    TenantTruckMovementLog.objects.select_related(
                        'from_location_point',
                        'to_location_point',
                        'truck',
                        'driver',
                    )
                    .get(pk=movement.pk)
                )

        return {
            'empty_move': _project_movement_response(
                movement,
                request=request,
                workflow_started=workflow_started,
            ),
        }

    @staticmethod
    def _auto_start_movement(
        *,
        movement: Any,
        driver: Any,
        tenant_user: Any,
        truck: Any,
        tenant_schema: str,
        jwt_payload: Mapping[str, Any],
        notes: str,
        client_action_id: str,
        latitude: Any,
        longitude: Any,
    ) -> bool:
        em1 = TenantOperationAction.objects.filter(
            action_code__iexact='EM1',
            status=TenantOperationAction.Status.ACTIVE,
        ).first()
        if em1 is None:
            return False

        driver_pk_val = driver_pk(driver)
        guard_ctx = MobileExecutionContext(
            driver=driver,
            tenant_user=tenant_user,
            tenant_schema=tenant_schema,
            driver_id=str(driver_pk_val or ''),
            user_id=str(getattr(tenant_user, 'pk', '') or ''),
            jwt_driver_id=str(jwt_payload.get('driver_id') or '') or None,
        )

        lat_str = '' if latitude is None else str(latitude)[:32]
        lng_str = '' if longitude is None else str(longitude)[:32]

        try:
            with mobile_execution_guard(guard_ctx):
                ActionExecutionService.execute_driver_action(
                    operation_action=em1,
                    movement=movement,
                    truck=truck,
                    driver=driver,
                    tenant_user=tenant_user,
                    created_by_label=_driver_label(driver),
                    notes=notes,
                    source='Mobile',
                    source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                    source_ref=client_action_id,
                    idempotency_key=client_action_id,
                    latitude=lat_str,
                    longitude=lng_str,
                    skip_recent_duplicate_guard=bool(client_action_id),
                    sync_shipment_after=False,
                )
        except DjangoValidationError:
            return False
        return True
