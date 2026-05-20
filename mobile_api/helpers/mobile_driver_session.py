"""
mobile_api/helpers/mobile_driver_session.py

Canonical **per-request** validation for mobile driver JWT access sessions.

Used by ``MobileJWTAuthentication`` (and ``authenticate_request``) so every
authenticated API call re-checks tenant workspace state: active non-deleted
user, active ``DriverMaster`` link, optional JWT↔DB claim binding, and **tenant
hint** consistency with the token's ``tenant_schema`` (body / header /
``request.tenant`` via ``resolve_tenant_hint_for_mobile_jwt``).

When ``MOBILE_API_JWT_REQUIRE_TENANT_HINT`` is true, a resolvable tenant context is
required: optional ``X-Tenant-ID`` / body ``tenant_id`` / ``request.tenant``, or
otherwise the JWT's own ``tenant_schema`` (Bearer-only mobile clients).

Admin disabling a driver or user takes effect on the **next** request because
validation always reads current DB rows (no caching of driver status).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from mobile_api.helpers.mobile_tenant import (
    get_mobile_tenant_schema_from_request,
    resolve_tenant_hint_for_mobile_jwt,
)
from mobile_api.helpers.security_audit import (
    client_ip_from_request as _sec_client_ip,
    log_mobile_security_event,
)

if TYPE_CHECKING:
    from tenant_workspace.models import DriverMaster, TenantUser

logger = logging.getLogger('mobile_api')

# (tenant_user, driver, error_message, error_code) — last two None on success
MobileDriverResolveResult = tuple[
    'TenantUser | None',
    'DriverMaster | None',
    object | None,
    str | None,
]


def get_mobile_request_tenant_schema(request) -> str:
    """
    Resolve tenant schema from ``request.tenant`` / ``X-Tenant-ID`` (unified).

    Returns '' when unresolved, on invalid identifiers, or on cross-source
    mismatch (see ``resolve_mobile_auth_tenant_context``).
    """
    if request is None:
        return ''
    return get_mobile_tenant_schema_from_request(request)


def _strict_claim_binding() -> bool:
    return bool(getattr(settings, 'MOBILE_API_JWT_STRICT_CLAIM_BINDING', True))


def _allowed_driver_role(role_name: str) -> bool:
    """
    Optional allow-list from ``MOBILE_API_DRIVER_ROLE_ALLOWLIST`` (CSV).

    When unset/empty, any ``TenantUser`` with an active linked ``DriverMaster``
    is accepted (driver link is the source of truth).
    """
    raw = (getattr(settings, 'MOBILE_API_DRIVER_ROLE_ALLOWLIST', '') or '').strip()
    if not raw:
        return True
    allowed = {p.strip().casefold() for p in raw.split(',') if p.strip()}
    return (role_name or '').strip().casefold() in allowed


def resolve_mobile_driver_session(
    request,
    payload: dict,
    *,
    forced_tenant_hint: str = '',
    body_tenant_id: str = '',
) -> MobileDriverResolveResult:
    """
    Resolve ``TenantUser`` + ``DriverMaster`` for a verified JWT payload.

    On success returns ``(tenant_user, driver, None, None)``.
    On failure returns ``(None, None, error_message, error_code)`` where
    ``error_message`` is a ``gettext_lazy`` string suitable for API responses.
    """
    from tenant_workspace.models import DriverMaster, TenantUser

    user_id = str(payload.get('user_id') or '').strip()
    tenant_schema = str(payload.get('tenant_schema') or '').strip()
    if not user_id or not tenant_schema:
        return None, None, _('mobile.auth.token_invalid'), 'token_invalid'

    hint, herr = resolve_tenant_hint_for_mobile_jwt(
        request,
        forced_tenant_hint=forced_tenant_hint,
        body_tenant_id=body_tenant_id,
        token_tenant_schema=tenant_schema,
    )
    if herr == 'invalid_tenant':
        return None, None, _('mobile.auth.invalid_tenant'), 'invalid_tenant'
    if herr == 'tenant_mismatch':
        return None, None, _('mobile.auth.tenant_mismatch'), 'tenant_mismatch'

    require_hint = bool(
        getattr(settings, 'MOBILE_API_JWT_REQUIRE_TENANT_HINT', True),
    )
    if require_hint and not (hint or '').strip():
        return None, None, _('mobile.auth.tenant_required'), 'tenant_required'

    hint = (hint or '').strip()
    if hint and hint != tenant_schema:
        logger.warning(
            'mobile.driver_auth tenant_mismatch token_schema=%s request_hint=%s',
            tenant_schema,
            hint,
        )
        try:
            log_mobile_security_event(
                'jwt_tenant_hint_mismatch',
                schema=tenant_schema,
                user_id=user_id,
                ip=_sec_client_ip(request),
                reason=f'hint={hint[:64]}',
            )
        except Exception:
            pass
        return None, None, _('mobile.auth.tenant_mismatch'), 'tenant_mismatch'

    try:
        with schema_context(tenant_schema):
            driver = (
                DriverMaster.objects.filter(user_account_id=user_id)
                .select_related('user_account')
                .first()
            )
    except Exception:
        return None, None, _('mobile.auth.token_invalid'), 'token_invalid'

    if driver is None:
        return None, None, _('mobile.auth.not_a_driver'), 'not_a_driver'
    if str(driver.driver_status) != DriverMaster.Status.ACTIVE:
        return None, None, _('mobile.auth.driver_inactive'), 'driver_inactive'

    tu = getattr(driver, 'user_account', None)
    if tu is None:
        return None, None, _('mobile.auth.not_a_driver'), 'not_a_driver'
    if getattr(tu, 'is_deleted', False):
        return None, None, _('mobile.auth.account_deleted'), 'account_deleted'
    if tu.status != TenantUser.Status.ACTIVE:
        return None, None, _('mobile.auth.account_inactive'), 'account_inactive'

    if not _allowed_driver_role(tu.role_name or ''):
        return None, None, _('mobile.auth.forbidden'), 'forbidden'

    claim_tv = payload.get('token_version')
    db_tv = int(getattr(tu, 'mobile_token_version', 0) or 0)
    if claim_tv is None:
        if db_tv != 0:
            return None, None, _('mobile.auth.token_invalid'), 'token_invalid'
    else:
        try:
            if int(claim_tv) != db_tv:
                return None, None, _('mobile.auth.token_invalid'), 'token_invalid'
        except (TypeError, ValueError):
            return None, None, _('mobile.auth.token_invalid'), 'token_invalid'

    if _strict_claim_binding():
        p_email = (payload.get('email') or '').strip().lower()
        if p_email and p_email != (tu.email or '').strip().lower():
            logger.warning(
                'mobile.driver_auth email_claim_mismatch user_id=%s',
                user_id,
            )
            return None, None, _('mobile.auth.token_invalid'), 'token_invalid'
        p_did = str(payload.get('driver_id') or '').strip()
        if p_did and p_did != str(driver.driver_id):
            logger.warning(
                'mobile.driver_auth driver_id_claim_mismatch user_id=%s',
                user_id,
            )
            return None, None, _('mobile.auth.token_invalid'), 'token_invalid'
        p_role = (payload.get('role_name') or '').strip()
        if p_role and p_role != (tu.role_name or '').strip():
            logger.warning(
                'mobile.driver_auth role_claim_mismatch user_id=%s',
                user_id,
            )
            return None, None, _('mobile.auth.token_invalid'), 'token_invalid'

    return tu, driver, None, None


def load_mobile_driver_subject(
    request,
    payload: dict,
    *,
    forced_tenant_hint: str = '',
    body_tenant_id: str = '',
) -> tuple['TenantUser', 'DriverMaster']:
    """
    Load ``TenantUser`` + ``DriverMaster`` for a verified access-token payload.

    Raises ``rest_framework.exceptions.AuthenticationFailed`` on any violation
    (same contract as ``MobileJWTAuthentication``).
    """
    from rest_framework.exceptions import AuthenticationFailed

    tu, driver, err, code = resolve_mobile_driver_session(
        request,
        payload,
        forced_tenant_hint=forced_tenant_hint,
        body_tenant_id=body_tenant_id,
    )
    if err is not None:
        raise AuthenticationFailed(err, code=code or 'token_invalid')
    return tu, driver


def mobile_driver_session_valid_for_programmatic_auth(
    request,
    payload: dict,
) -> bool:
    """
    Non-raising check for ``authenticate_request`` / ``authenticate_refresh_request``.

    Returns False on any validation failure.
    """
    _tu, _dr, err, _code = resolve_mobile_driver_session(request, payload)
    return err is None
