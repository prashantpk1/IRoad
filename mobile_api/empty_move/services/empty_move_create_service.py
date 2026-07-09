"""
Create driver-initiated empty truck movements (On Call mode).

PCS §5.1 — driver selects a reason and presses Start with device GPS.
Departure (``from_*``) is stored at create; arrival (``to_*``) is stamped when
the complete-movement workflow action executes with GPS.
"""
from __future__ import annotations

import logging
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
from mobile_api.dashboard.selectors.movement_selection_policy import (
    is_active_empty_move,
)
from mobile_api.empty_move.exceptions import EmptyMoveError
from mobile_api.helpers.mobile_execution_guard import (
    MobileExecutionContext,
    mobile_execution_guard,
)
from mobile_api.job_detail.guards.ownership import driver_pk
from mobile_api.job_detail.projections.job_location_projection import (
    _empty_move_arrival_endpoint_block,
    gps_empty_move_endpoint_block,
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

logger = logging.getLogger('mobile_api.empty_move')
_DEBUG = '[EMPTY_MOVE_DEBUG]'


def _log_debug(step: str, **fields) -> None:
    parts = [f'{_DEBUG} {step}']
    for key, value in fields.items():
        parts.append(f'{key}={value!r}')
    line = ' | '.join(parts)
    logger.warning(line)
    print(line, flush=True)


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
            _log_debug('truck_not_found', truck_id=truck_id, driver_id=getattr(driver, 'pk', ''))
            raise EmptyMoveError(
                str(_('mobile.empty_move.truck_not_found')),
                code='truck_not_found',
                http_status=404,
                message_key='mobile.empty_move.truck_not_found',
            )
        _log_debug('truck_resolved', source='payload_truck_id', truck_id=truck.pk)
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
        _log_debug(
            'truck_resolved',
            source='assignment_history',
            truck_id=assignment.truck_id,
            driver_id=getattr(driver, 'pk', ''),
        )
        return assignment.truck

    driver_pk_val = driver_pk(driver)
    if driver_pk_val is not None:
        truck = TruckMaster.objects.filter(default_driver_id=driver_pk_val).first()
        if truck is not None:
            _log_debug(
                'truck_resolved',
                source='default_driver_on_truck',
                truck_id=truck.pk,
                driver_id=driver_pk_val,
            )
            return truck
    _log_debug(
        'truck_missing',
        driver_id=getattr(driver, 'pk', ''),
        driver_pk_val=driver_pk_val,
        had_open_assignment=bool(assignment),
    )
    return None


def _resolve_location(location_id) -> TenantLocationMaster | None:
    if location_id is None:
        return None
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


def _assert_on_call_state(
    driver: Any,
    *,
    tenant_schema: str,
    request: Any | None = None,
) -> None:
    booking_sel = DashboardBookingSelector().select_current_driver_booking(
        driver,
        tenant_schema=tenant_schema,
    )
    if booking_sel is not None:
        _log_debug(
            'blocked_active_booking',
            driver_id=getattr(driver, 'pk', ''),
            tenant_schema=tenant_schema,
        )
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
    if existing is not None and is_active_empty_move(existing.movement):
        _log_debug(
            'blocked_existing_empty_move',
            driver_id=getattr(driver, 'pk', ''),
            tenant_schema=tenant_schema,
            movement_id=getattr(existing.movement, 'pk', ''),
        )
        movement = existing.movement
        if hasattr(movement, 'refresh_from_db'):
            movement.refresh_from_db()
        resume_payload = {
            'empty_move': _project_movement_response(
                movement,
                request=request,
                workflow_started=existing.movement_stage not in ('', 'created'),
            ),
            'resume_existing': True,
            'resume_job': {
                'job_type': 'movement',
                'job_id': str(
                    getattr(movement, 'movement_id', None) or getattr(movement, 'pk', '') or ''
                ),
                'job_no': str(getattr(movement, 'movement_no', '') or ''),
                'entity_type': 'movement',
            },
        }
        raise EmptyMoveError(
            str(_('mobile.empty_move.already_active')),
            code='empty_move_already_active',
            http_status=409,
            message_key='mobile.empty_move.already_active',
            data=resume_payload,
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


def _resolve_destination_gps(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Optional planned arrival GPS from empty-move create payload."""
    return _coord_str(payload.get('to_latitude')), _coord_str(payload.get('to_longitude'))


def _movement_endpoint_projection(
    movement: Any,
    side: str,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    if side == 'to':
        return _empty_move_arrival_endpoint_block(movement, request=request)
    if side == 'from':
        block = gps_empty_move_endpoint_block(
            movement,
            'from',
            request=request,
        )
        if block:
            return block
    prefix = f'{side}_'
    return serialize_location_point(
        getattr(movement, f'{prefix}location_point', None),
        request=request,
        map_link=getattr(movement, f'{prefix}location_map_link', '') or '',
        address=getattr(movement, f'{prefix}location_address', '') or '',
        latitude=getattr(movement, f'{prefix}latitude', '') or '',
        longitude=getattr(movement, f'{prefix}longitude', '') or '',
    )


def _empty_move_workflow_contract() -> dict[str, Any]:
    """Mobile routing contract — GPS on Start Job (from) and End Job (to)."""
    return {
        'route_capture_mode': 'gps',
        'manual_location_picker': False,
        'departure_captured_on': 'start_action',
        'arrival_captured_on': 'complete_action',
        'gps_endpoints': ['from', 'to'],
        'workflow_steps_after_reason': ['start_with_gps', 'movement_actions'],
    }


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
        'from_location': _movement_endpoint_projection(movement, 'from', request=request),
        'to_location': _movement_endpoint_projection(movement, 'to', request=request),
        'workflow_started': workflow_started,
        'workflow_contract': _empty_move_workflow_contract(),
    }


class EmptyMoveCreateService:
    """Create empty move rows; driver fires EM1 (Start) from the workflow screen."""

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
            _assert_on_call_state(driver, tenant_schema=schema, request=request)

            truck = _resolve_driver_truck(driver, payload.get('truck_id'))
            if truck is None:
                _log_debug(
                    'raising_truck_required',
                    driver_id=getattr(driver, 'pk', ''),
                    tenant_schema=schema,
                )
                raise EmptyMoveError(
                    str(_('mobile.empty_move.truck_required')),
                    code='truck_required',
                    http_status=400,
                    message_key='mobile.empty_move.truck_required',
                )

            from_location = _resolve_location(payload.get('from_location_id'))
            to_location = _resolve_location(payload.get('to_location_id'))

            movement_date = payload.get('movement_date') or timezone.localdate()
            created_by = _driver_label(driver)

            from_address = str(payload.get('from_address') or '').strip()
            to_address = str(payload.get('to_address') or '').strip()
            start_lat, start_lng = _resolve_start_gps(payload)
            to_lat, to_lng = _resolve_destination_gps(payload)

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
                    to_latitude=to_lat,
                    to_longitude=to_lng,
                    from_address=from_address,
                    to_address=to_address,
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
                workflow_started=False,
            ),
            'workflow_contract': _empty_move_workflow_contract(),
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
        from mobile_api.helpers.empty_move_action_resolver import (
            resolve_empty_move_start_action,
        )

        em1 = resolve_empty_move_start_action(tenant_schema)
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
