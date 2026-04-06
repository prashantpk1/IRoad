"""
JWT helpers for tenant workspace and Control Panel impersonation (HS256).

Tenant apps must use the same signing key as CP: ``settings.TENANT_JWT_SIGNING_KEY``
or fall back to ``SECRET_KEY``. Claims are not encrypted; validate ``exp`` and
``typ`` on every request.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings


def _signing_key():
    key = getattr(settings, 'TENANT_JWT_SIGNING_KEY', '') or ''
    key = key.strip()
    return key or settings.SECRET_KEY


def sign_tenant_access_jwt(
        *,
        tenant_id,
        subject,
        token_type='tenant_access',
        ttl_seconds=900,
        jti=None,
        extra_claims=None):
    """
    Access token for tenant human users. Always includes ``tenant_id`` and ``jti``
    (for Redis kill-switch registration via ``/api/v1/tenant/sessions/register/``).
    """
    now = datetime.now(timezone.utc)
    token_id = jti or str(uuid.uuid4())
    payload = {
        'jti': token_id,
        'tenant_id': str(tenant_id),
        'sub': str(subject),
        'typ': token_type,
        'iat': int(now.timestamp()),
        'exp': int((now + timedelta(seconds=max(60, int(ttl_seconds)))).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, _signing_key(), algorithm='HS256'), token_id


def sign_cp_impersonation_jwt(tenant, admin_user, ttl_minutes=15):
    """Short-lived token for CP root 'Login As' handoff to tenant portal."""
    now = datetime.now(timezone.utc)
    ttl_min = max(1, min(int(ttl_minutes), 60))
    token_id = str(uuid.uuid4())
    payload = {
        'jti': token_id,
        'tenant_id': str(tenant.tenant_id),
        'typ': 'cp_impersonation',
        'cp_impersonator_admin_id': str(admin_user.pk),
        'cp_impersonator_email': admin_user.email,
        'iat': int(now.timestamp()),
        'exp': int((now + timedelta(minutes=ttl_min)).timestamp()),
    }
    return jwt.encode(payload, _signing_key(), algorithm='HS256')
