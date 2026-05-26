"""
mobile_api/job_detail/services/job_detail_driver_resolver.py

Resolve authenticated driver session for Job Detail requests.
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.rbac import get_mobile_jwt_payload, has_driver_id_claim


def resolve_job_detail_driver(request) -> tuple[Any | None, str | None, str | None]:
    """
    Load ``DriverMaster`` for Job Detail inside tenant schema.

    Returns ``(driver, error_message, error_code)``.
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


def tenant_schema_for_request(request) -> str:
    """JWT tenant schema — tenant isolation for ``schema_context``."""
    payload = get_mobile_jwt_payload(request)
    return str(payload.get('tenant_schema') or '').strip()
