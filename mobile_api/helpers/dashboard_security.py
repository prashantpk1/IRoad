"""
mobile_api/helpers/dashboard_security.py

Multi-tenant, driver-scoped security for the home dashboard module.

Guarantees:
- All ORM reads use the authenticated driver's PK (never JWT alone).
- Shipment/movement rows are validated against driver scope before projection.
- Optional response sanitization strips IDs that fail ownership checks.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from django.utils.translation import gettext as _

from mobile_api.helpers.dashboard_ownership import (
    DriverOwnershipScope,
    preload_driver_ownership_scope,
)
from mobile_api.helpers.operational_status import (
    driver_movement_scope_q,
    driver_shipment_scope_q,
)
from mobile_api.helpers.mobile_tenant import resolve_active_tenant_registry
from mobile_api.rbac import get_mobile_jwt_payload

logger = logging.getLogger('mobile_api')

DASHBOARD_API_PREFIX = '/api/v1/mobile/driver/dashboard'
DASHBOARD_CAPABILITY = 'mobile.driver.dashboard'


@dataclass(frozen=True)
class SecureDashboardContext:
    """Bound principal for one dashboard request (tenant schema + driver row)."""

    driver: Any
    tenant_user: Any
    tenant_schema: str
    driver_id: str
    user_id: str
    jwt_driver_id: str | None = None


def _normalize_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value).strip()))
    except (TypeError, ValueError):
        return None


def validate_dashboard_tenant_binding(request, *, expected_schema: str) -> bool:
    """
    Reject cross-tenant hints on dashboard routes.

    When ``X-Tenant-ID`` / body tenant is present it must resolve to
    ``expected_schema`` (JWT ``tenant_schema``).
    """
    if not (expected_schema or '').strip():
        return False

    from mobile_api.helpers.mobile_tenant import resolve_mobile_auth_tenant_context

    ctx_schema, err = resolve_mobile_auth_tenant_context(request, body_tenant_id='')
    if err in ('invalid_tenant', 'tenant_mismatch'):
        return False
    ctx = (ctx_schema or '').strip()
    if ctx and ctx != expected_schema.strip():
        try:
            from mobile_api.helpers.security_audit import (
                client_ip_from_request,
                log_mobile_security_event,
            )

            log_mobile_security_event(
                'dashboard_tenant_hint_mismatch',
                schema=expected_schema,
                ip=client_ip_from_request(request),
                reason=f'hint_schema={ctx[:64]}',
            )
        except Exception:
            pass
        logger.warning(
            'dashboard_security tenant_hint_mismatch token_schema=%s hint=%s',
            expected_schema,
            ctx,
        )
        return False
    return True


def assert_jwt_driver_matches_row(
    *,
    jwt_payload: dict | None,
    driver,
) -> bool:
    """True when JWT ``driver_id`` claim matches the resolved ``DriverMaster`` row."""
    if not jwt_payload:
        return True
    claim = str(jwt_payload.get('driver_id') or '').strip()
    if not claim:
        return False
    return claim == str(getattr(driver, 'driver_id', driver.pk))


def resolve_secure_dashboard_context(
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    jwt_payload: dict | None = None,
) -> dict[str, Any]:
    """
    Load tenant user + driver and enforce dashboard security invariants.

    Returns ``{'success': True, 'ctx': SecureDashboardContext}`` or error dict.
    """
    from mobile_api.services.driver_profile_service import _resolve_driver_context

    pl = jwt_payload if jwt_payload is not None else (
        get_mobile_jwt_payload(request) if request is not None else {}
    )
    token_schema = str(pl.get('tenant_schema') or '').strip()
    if token_schema and tenant_schema.strip() != token_schema:
        return {'success': False, 'error': _('mobile.auth.tenant_mismatch')}

    if request is not None and token_schema:
        if not validate_dashboard_tenant_binding(
            request,
            expected_schema=token_schema,
        ):
            return {'success': False, 'error': _('mobile.auth.tenant_mismatch')}

    base = _resolve_driver_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        jwt_email=pl.get('email'),
    )
    if not base.get('success'):
        return base

    driver = base['driver']
    if not assert_jwt_driver_matches_row(jwt_payload=pl, driver=driver):
        logger.warning(
            'dashboard_security driver_id_mismatch schema=%s user_id=%s',
            tenant_schema,
            user_id,
        )
        return {'success': False, 'error': _('mobile.auth.unauthorized')}

    ctx = SecureDashboardContext(
        driver=driver,
        tenant_user=base['tenant_user'],
        tenant_schema=tenant_schema.strip(),
        driver_id=str(driver.driver_id),
        user_id=str(user_id),
        jwt_driver_id=str(pl.get('driver_id') or '').strip() or None,
    )
    return {'success': True, 'ctx': ctx}


def shipment_queryset_for_driver(driver):
    """Tenant-scoped shipments visible to this driver (direct or booking assignment)."""
    from tenant_workspace.models import TenantShipment

    return TenantShipment.objects.filter(driver_shipment_scope_q(driver))


def movement_queryset_for_driver(driver):
    """Tenant-scoped movements owned by this driver."""
    from tenant_workspace.models import TenantTruckMovementLog

    return TenantTruckMovementLog.objects.filter(driver_movement_scope_q(driver))


def driver_owns_shipment_id(
    driver,
    shipment_id: str | None,
    *,
    scope: DriverOwnershipScope | None = None,
) -> bool:
    sid = _normalize_uuid(shipment_id)
    if not sid:
        return False
    if scope is not None:
        return scope.owns_shipment(sid)
    return shipment_queryset_for_driver(driver).filter(pk=sid).exists()


def driver_owns_movement_id(
    driver,
    movement_id: str | None,
    *,
    scope: DriverOwnershipScope | None = None,
) -> bool:
    mid = _normalize_uuid(movement_id)
    if not mid:
        return False
    if scope is not None:
        return scope.owns_movement(mid)
    return movement_queryset_for_driver(driver).filter(pk=mid).exists()


def assert_shipment_row_owned(driver, shipment, *, scope=None) -> bool:
    if shipment is None:
        return False
    sid = str(getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', ''))
    return driver_owns_shipment_id(driver, sid, scope=scope)


def assert_movement_row_owned(driver, movement, *, scope=None) -> bool:
    if movement is None:
        return False
    mid = str(getattr(movement, 'pk', None) or getattr(movement, 'movement_id', ''))
    return driver_owns_movement_id(driver, mid, scope=scope)


def action_log_queryset_for_driver(driver):
    from tenant_workspace.models import TenantOperationActionLog

    return TenantOperationActionLog.objects.filter(driver_id=driver.pk)


def inbox_queryset_for_driver(driver):
    from tenant_workspace.models import DriverMobileNotification

    return DriverMobileNotification.objects.filter(driver=driver)


def sanitize_activity_items(
    *,
    items: list[dict[str, Any]],
    scope: DriverOwnershipScope,
) -> list[dict[str, Any]]:
    """Drop activity rows referencing shipments/movements outside driver scope."""
    safe: list[dict[str, Any]] = []
    for row in items:
        sid = row.get('shipment_id')
        mid = row.get('movement_id')
        if sid and not scope.owns_shipment(sid):
            continue
        if mid and not scope.owns_movement(mid):
            continue
        safe.append(row)
    return safe


def sanitize_notification_items(
    *,
    items: list[dict[str, Any]],
    scope: DriverOwnershipScope,
) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for row in items:
        sid = row.get('shipment_id')
        mid = row.get('movement_id')
        if sid and not scope.owns_shipment(sid):
            continue
        if mid and not scope.owns_movement(mid):
            continue
        safe.append(row)
    return safe


def sanitize_quick_actions(
    *,
    actions: list[dict[str, Any]],
    scope: DriverOwnershipScope,
) -> list[dict[str, Any]]:
    """Remove shipment/movement IDs from actions when ownership cannot be verified."""
    out: list[dict[str, Any]] = []
    for action in actions:
        row = dict(action)
        sid = row.pop('shipment_id', None) if 'shipment_id' in row else None
        mid = row.pop('movement_id', None) if 'movement_id' in row else None
        if sid and scope.owns_shipment(sid):
            row['shipment_id'] = sid
        if mid and scope.owns_movement(mid):
            row['movement_id'] = mid
        out.append(row)
    return out


def sanitize_dashboard_payload(
    *,
    driver,
    payload: dict[str, Any],
    ownership_scope: DriverOwnershipScope | None = None,
) -> dict[str, Any]:
    """
    Defense-in-depth: strip cross-driver entity IDs from a built dashboard dict.
    """
    from django.conf import settings

    if not getattr(settings, 'MOBILE_API_DASHBOARD_ENFORCE_OWNERSHIP_SANITIZE', True):
        return payload

    scope = ownership_scope or preload_driver_ownership_scope(driver)
    data = dict(payload)
    driver_id = str(getattr(driver, 'driver_id', driver.pk))

    ds = data.get('driver_summary') or {}
    if str(ds.get('driver_id') or '') not in ('', driver_id):
        ds = dict(ds)
        ds['driver_id'] = driver_id
        data['driver_summary'] = ds

    welcome = data.get('welcome') or {}
    w_driver = welcome.get('driver') or {}
    if w_driver and str(w_driver.get('driver_id') or '') not in ('', driver_id):
        welcome = dict(welcome)
        w_driver = dict(w_driver)
        w_driver['driver_id'] = driver_id
        welcome['driver'] = w_driver
        data['welcome'] = welcome

    if 'recent_activity' in data and isinstance(data['recent_activity'], list):
        data['recent_activity'] = sanitize_activity_items(
            items=data['recent_activity'],
            scope=scope,
        )

    ns = data.get('notifications_summary') or {}
    if ns.get('items'):
        ns = dict(ns)
        ns['items'] = sanitize_notification_items(
            items=list(ns.get('items') or []),
            scope=scope,
        )
        data['notifications_summary'] = ns

    if data.get('quick_actions'):
        data['quick_actions'] = sanitize_quick_actions(
            actions=list(data['quick_actions']),
            scope=scope,
        )

    cj = data.get('current_job') or {}
    if cj.get('has_active_job'):
        sid = cj.get('shipment_id')
        if sid and not scope.owns_shipment(sid):
            from mobile_api.services.driver_dashboard_current_job import (
                empty_current_job_snapshot,
            )

            data['current_job'] = empty_current_job_snapshot()

    return data


def resolve_tenant_schema_from_header(tenant_hint: str) -> str | None:
    """Map ``X-Tenant-ID`` to ``schema_name`` when hint is a registry identifier."""
    reg = resolve_active_tenant_registry(tenant_hint)
    if reg is None:
        return None
    return str(getattr(reg, 'schema_name', '') or '').strip() or None
