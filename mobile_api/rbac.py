"""
mobile_api/rbac.py

Enterprise-style **role + capability** model for the mobile API.

- **Role groups** (derived from JWT claims + ``TenantUser.role_name``) are:
  ``driver``, ``dispatcher``, ``tenant_admin``.
- **Capabilities** map API surfaces to one or more role groups so new modules
  add a row in ``CAPABILITY_GROUPS`` without rewriting permission classes.

Authorization runs in DRF permission classes (and optional decorators for
non-DRF views). JWT refresh/access must include ``role_name`` and, for driver
sessions, ``driver_id`` (see ``build_token_claims``).
"""
from __future__ import annotations

import logging
from typing import Any, FrozenSet

from django.conf import settings

logger = logging.getLogger('mobile_api')

# capability_id -> role group keys (union: user may satisfy any listed group)
CAPABILITY_GROUPS: dict[str, tuple[str, ...]] = {
    # Driver self-service (requires driver principal + driver role policy)
    'mobile.driver.profile': ('driver',),
    'mobile.driver.organization': ('driver',),
    'mobile.driver.dashboard': ('driver',),
    'mobile.driver.job_detail': ('driver',),
    'mobile.driver.execute': ('driver',),
    'mobile.driver.auth_session': ('driver',),
    # Operational / back-office style mobile modules (dispatcher + tenant admin)
    'mobile.operations.read': ('dispatcher', 'tenant_admin'),
    'mobile.operations.write': ('dispatcher', 'tenant_admin'),
    # Strict tenant administration
    'mobile.tenant.admin': ('tenant_admin',),
}


def get_mobile_jwt_payload(request: Any) -> dict:
    """Return verified access payload attached by ``MobileJWTAuthentication``."""
    auth = getattr(request, 'auth', None)
    if isinstance(auth, dict):
        return auth
    user = getattr(request, 'user', None)
    pl = getattr(user, 'payload', None)
    return pl if isinstance(pl, dict) else {}


def _csv_role_set(setting_name: str, default_csv: str) -> FrozenSet[str]:
    raw = (getattr(settings, setting_name, None) or default_csv or '').strip()
    return frozenset(x.strip().casefold() for x in raw.split(',') if x.strip())


def driver_role_names() -> FrozenSet[str]:
    """
    Roles that may use **driver** mobile endpoints when a ``driver_id`` claim exists.

    ``MOBILE_API_RBAC_DRIVER_ROLE_NAMES`` overrides defaults when non-blank.
    Values from ``MOBILE_API_DRIVER_ROLE_ALLOWLIST`` (auth layer) are **unioned**
    so a single CSV can govern both JWT session auth and RBAC driver views.
    """
    raw = (getattr(settings, 'MOBILE_API_RBAC_DRIVER_ROLE_NAMES', None) or '').strip()
    base: set[str] = set()
    if raw:
        base.update(x.strip().casefold() for x in raw.split(',') if x.strip())
    else:
        base.update(
            x.strip().casefold()
            for x in (
                'Driver,Company Driver,Truck Driver,Driver User,Drivers'
            ).split(',')
            if x.strip()
        )
    allow = (getattr(settings, 'MOBILE_API_DRIVER_ROLE_ALLOWLIST', None) or '').strip()
    if allow:
        base.update(x.strip().casefold() for x in allow.split(',') if x.strip())
    return frozenset(base)


def dispatcher_role_names() -> FrozenSet[str]:
    return _csv_role_set(
        'MOBILE_API_RBAC_DISPATCHER_ROLE_NAMES',
        'Dispatcher,Dispatch Controller,Operations,Operations Dispatcher',
    )


def tenant_admin_role_names() -> FrozenSet[str]:
    return _csv_role_set(
        'MOBILE_API_RBAC_TENANT_ADMIN_ROLE_NAMES',
        'Administrator,Tenant Admin,Super Admin',
    )


def normalized_role_name(request: Any) -> str:
    return (get_mobile_jwt_payload(request).get('role_name') or '').strip().casefold()


def is_tenant_admin_role_name(role_name: str) -> bool:
    """True when ``role_name`` matches configured tenant-admin role CSV."""
    rn = (role_name or '').strip().casefold()
    if not rn:
        return False
    return rn in tenant_admin_role_names()


def compute_is_admin_claim(tenant_user) -> bool:
    """JWT ``is_admin`` flag (mirrors RBAC tenant-admin role names)."""
    return is_tenant_admin_role_name(getattr(tenant_user, 'role_name', '') or '')


def has_driver_id_claim(request: Any) -> bool:
    return bool(str(get_mobile_jwt_payload(request).get('driver_id') or '').strip())


def user_in_driver_group(request: Any) -> bool:
    """
    Driver mobile principal: non-empty ``driver_id`` claim.

    When ``MOBILE_API_DRIVER_ROLE_ALLOWLIST`` is empty, the linked ``DriverMaster``
    row validated at authentication is authoritative (supports tenant-specific
    role labels such as custom RBAC role names).
    """
    if not has_driver_id_claim(request):
        return False
    raw_allow = (
        getattr(settings, 'MOBILE_API_DRIVER_ROLE_ALLOWLIST', None) or ''
    ).strip()
    if not raw_allow:
        return True
    rn = normalized_role_name(request)
    return rn in driver_role_names()


def user_in_dispatcher_group(request: Any) -> bool:
    rn = normalized_role_name(request)
    disp = dispatcher_role_names()
    if not disp:
        return False
    return rn in disp


def user_in_tenant_admin_group(request: Any) -> bool:
    payload = get_mobile_jwt_payload(request)
    if bool(payload.get('is_admin')):
        return True
    return normalized_role_name(request) in tenant_admin_role_names()


def role_groups_for_principal(request: Any) -> FrozenSet[str]:
    """Role group tags satisfied by the current JWT (may be multiple)."""
    groups: set[str] = set()
    if user_in_driver_group(request):
        groups.add('driver')
    if user_in_dispatcher_group(request):
        groups.add('dispatcher')
    if user_in_tenant_admin_group(request):
        groups.add('tenant_admin')
    return frozenset(groups)


def request_has_capability(request: Any, capability_id: str) -> bool:
    required = CAPABILITY_GROUPS.get(capability_id)
    if required is None:
        logger.warning('Unknown mobile capability_id=%s', capability_id)
        return False
    principal = role_groups_for_principal(request)
    return bool(principal.intersection(required))


def list_granted_capabilities(request: Any) -> list[str]:
    """Sorted capability ids the current principal may invoke."""
    granted: list[str] = []
    for cap in sorted(CAPABILITY_GROUPS):
        if request_has_capability(request, cap):
            granted.append(cap)
    return granted


def register_mobile_capability(capability_id: str, role_groups: tuple[str, ...]) -> None:
    """
    Register or override a capability mapping at startup (e.g. ``AppConfig.ready``).

    ``role_groups`` entries must be subset of:
    ``driver``, ``dispatcher``, ``tenant_admin``.
    """
    bad = set(role_groups) - {'driver', 'dispatcher', 'tenant_admin'}
    if bad:
        raise ValueError(f'Invalid role groups for {capability_id}: {bad}')
    CAPABILITY_GROUPS[capability_id] = tuple(role_groups)


def build_mobile_rbac_snapshot(request: Any) -> dict[str, Any]:
    """Structured RBAC payload for serializers / profile ``permissions`` block."""
    payload = get_mobile_jwt_payload(request)
    groups = role_groups_for_principal(request)
    return {
        'role_name': payload.get('role_name') or '',
        'is_admin_claim': bool(payload.get('is_admin')),
        'driver_id': str(payload.get('driver_id') or '').strip() or None,
        'role_groups': sorted(groups),
        'capabilities': list_granted_capabilities(request),
    }
