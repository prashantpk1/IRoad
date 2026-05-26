"""
mobile_api/dashboard/services/driver_resolver.py

Resolve and validate the tenant ``DriverMaster`` for dashboard requests.
"""
from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied

from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.rbac import get_mobile_jwt_payload, has_driver_id_claim
from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
from mobile_api.dashboard.selectors import movement_selection_policy as movement_policy


def resolve_dashboard_driver(request) -> tuple[Any | None, str | None, str | None]:
    """
    Load driver for dashboard orchestration inside tenant schema.

    Returns ``(driver, error_message, error_code)`` — mirrors mobile session resolver.
    """
    payload = get_mobile_jwt_payload(request)
    if not has_driver_id_claim(request):
        return None, 'Driver session required.', 'driver_role_required'

    _tenant_user, driver, err_msg, err_code = resolve_mobile_driver_session(
        request,
        payload,
    )
    if driver is None:
        return None, str(err_msg or 'Unauthorized'), str(err_code or 'unauthorized')
    return driver, None, None


def assert_dashboard_scope_ownership(
    driver: Any,
    *,
    active_shipment: Any | None = None,
    active_movement: Any | None = None,
    active_booking: Any | None = None,
) -> None:
    """
    Defense-in-depth: selected rows must belong to the authenticated driver.

    Raises ``PermissionDenied`` when a selection violates assignment rules.
    """
    driver_pk = booking_policy._driver_pk(driver)
    if driver_pk is None:
        raise PermissionDenied('driver_not_resolved')

    if active_booking is not None and not booking_policy.driver_has_booking_assignment(
        driver, active_booking
    ):
        if active_shipment is None or not booking_policy.driver_owns_shipment_leg(
            driver, active_booking, active_shipment
        ):
            raise PermissionDenied('booking_not_assigned_to_driver')

    if active_shipment is not None:
        shipment_driver = getattr(active_shipment, 'driver_id', None)
        if shipment_driver and shipment_driver != driver_pk:
            if active_booking is None or not booking_policy.driver_owns_shipment_leg(
                driver, active_booking, active_shipment
            ):
                raise PermissionDenied('shipment_not_assigned_to_driver')

    if active_movement is not None:
        if not movement_policy.driver_assigned_to_movement(driver, active_movement):
            raise PermissionDenied('movement_not_assigned_to_driver')


def tenant_schema_for_request(request) -> str:
    payload = get_mobile_jwt_payload(request)
    return str(payload.get('tenant_schema') or '').strip()
