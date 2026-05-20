"""
mobile_api/helpers/mobile_tenant.py

Canonical **tenant isolation** helpers for mobile APIs (registry resolution on
the public schema, hint aggregation from body / header / ``request.tenant``).

Used by auth views, ``MobileJWTAuthentication`` / ``mobile_driver_session``, and
``MobileApiTenantGateMiddleware`` so tenant selection is consistent and
cross-tenant spoof attempts (conflicting identifiers) are rejected in one place.
"""
from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger('mobile_api')

TenantResolveErr = Literal['invalid_tenant', 'tenant_mismatch'] | None


def resolve_active_tenant_registry(tenant_identifier: str):
    """
    Resolve ``TenantRegistry`` from tenant profile UUID or ``schema_name``.

    Returns None when unknown or subscriber ``account_status`` is not Active.
    """
    tid = (tenant_identifier or '').strip()
    if not tid:
        return None
    try:
        from iroad_tenants.models import TenantRegistry

        qs = TenantRegistry.objects.select_related('tenant_profile')
        reg = qs.filter(tenant_profile_id=tid).first()
        if reg is None:
            reg = qs.filter(schema_name=tid).first()
        if reg is None:
            return None
        profile = getattr(reg, 'tenant_profile', None)
        if profile and getattr(profile, 'account_status', None) != 'Active':
            return None
        return reg
    except Exception as exc:
        logger.error('resolve_active_tenant_registry error: %s', exc)
        return None


def resolve_mobile_auth_tenant_context(
    request,
    *,
    body_tenant_id: str = '',
) -> tuple[str, TenantResolveErr]:
    """
    Resolve a single subscriber ``schema_name`` for mobile auth endpoints.

    Precedence: JSON ``tenant_id`` (``body_tenant_id``) → ``X-Tenant-ID`` →
    ``request.tenant`` (e.g. ``TenantApiSchemaMiddleware`` on ``/api/v1/``).

    Returns:
        ``(schema_name, None)`` on success.
        ``('', 'invalid_tenant')`` when a supplied identifier does not resolve
        to an active subscriber.
        ``('', 'tenant_mismatch')`` when two sources resolve to different schemas
        (tenant spoof / misconfiguration).
        ``('', None)`` when no tenant hint is present.
    """
    if request is None:
        return '', None

    resolved_from_body: str | None = None
    resolved_from_header: str | None = None
    resolved_from_request_tenant: str | None = None

    b = (body_tenant_id or '').strip()
    if b:
        reg = resolve_active_tenant_registry(b)
        if reg is None:
            return '', 'invalid_tenant'
        resolved_from_body = str(reg.schema_name).strip()

    h = (request.headers.get('X-Tenant-ID') or '').strip()
    if h:
        reg = resolve_active_tenant_registry(h)
        if reg is None:
            return '', 'invalid_tenant'
        resolved_from_header = str(reg.schema_name).strip()

    tenant = getattr(request, 'tenant', None)
    rt = (getattr(tenant, 'schema_name', None) or '').strip()
    if rt:
        resolved_from_request_tenant = rt

    candidates: list[tuple[str, str]] = []
    if resolved_from_body:
        candidates.append((resolved_from_body, 'body'))
    if resolved_from_header:
        candidates.append((resolved_from_header, 'header'))
    if resolved_from_request_tenant:
        candidates.append((resolved_from_request_tenant, 'request.tenant'))

    schemas = [c[0] for c in candidates if c[0]]
    unique = list(dict.fromkeys(schemas))
    if len(unique) > 1:
        logger.warning(
            'mobile_tenant.auth_context_mismatch candidates=%s',
            candidates,
        )
        return '', 'tenant_mismatch'
    if len(unique) == 1:
        return unique[0], None
    return '', None


def merge_mobile_jwt_tenant_context(
    request,
    payload: dict | None,
    *,
    body_tenant_id: str = '',
) -> tuple[str, TenantResolveErr]:
    """
    Tenant schema for authenticated mobile calls with a verified JWT ``payload``.

    Optional ``tenant_id`` (body) / ``X-Tenant-ID`` / ``request.tenant`` must match
    the token's ``tenant_schema`` when present; otherwise the token's schema is used
    so clients do not need to send a tenant header on every request.
    """
    pl = payload or {}
    payload_ts = str(pl.get('tenant_schema') or '').strip()
    ctx_ts, terr = resolve_mobile_auth_tenant_context(
        request,
        body_tenant_id=body_tenant_id,
    )
    if terr:
        return '', terr
    ctx = (ctx_ts or '').strip()
    if ctx and payload_ts and ctx != payload_ts:
        logger.warning(
            'mobile_tenant.jwt_merge_mismatch ctx=%s token_schema=%s',
            ctx,
            payload_ts,
        )
        return '', 'tenant_mismatch'
    return ctx or payload_ts, None


def resolve_tenant_hint_for_mobile_jwt(
    request,
    *,
    forced_tenant_hint: str = '',
    body_tenant_id: str = '',
    token_tenant_schema: str = '',
) -> tuple[str, TenantResolveErr]:
    """
    Build the effective tenant **hint** for JWT access / refresh validation.

    Merges optional ``forced_tenant_hint`` (e.g. refresh body resolution) with
    request-derived context. Rejects conflicting hints vs. request identifiers.

    When no header/body hint exists, ``token_tenant_schema`` (from the verified
    JWT) is used so **Bearer-only** mobile calls still satisfy tenant resolution.
    """
    ctx_schema, ctx_err = resolve_mobile_auth_tenant_context(
        request,
        body_tenant_id=body_tenant_id,
    )
    if ctx_err == 'invalid_tenant':
        return '', 'invalid_tenant'
    if ctx_err == 'tenant_mismatch':
        return '', 'tenant_mismatch'

    forced = (forced_tenant_hint or '').strip()
    token_ts = (token_tenant_schema or '').strip()
    if forced:
        if ctx_schema and ctx_schema != forced:
            logger.warning(
                'mobile_tenant.jwt_hint_forced_mismatch ctx=%s forced=%s',
                ctx_schema,
                forced,
            )
            return '', 'tenant_mismatch'
        if token_ts and token_ts != forced:
            return '', 'tenant_mismatch'
        return forced, None
    if ctx_schema:
        if token_ts and ctx_schema != token_ts:
            logger.warning(
                'mobile_tenant.jwt_hint_ctx_vs_token ctx=%s token_schema=%s',
                ctx_schema,
                token_ts,
            )
            return '', 'tenant_mismatch'
        return ctx_schema, None
    if token_ts:
        return token_ts, None
    return '', None


def get_mobile_tenant_schema_from_request(request) -> str:
    """
    Best-effort schema string for callers that only need a string (legacy).

    On error or conflict returns '' (avoid silently picking a tenant).
    """
    if request is None:
        return ''
    schema, err = resolve_mobile_auth_tenant_context(request)
    if err:
        return ''
    return schema or ''
