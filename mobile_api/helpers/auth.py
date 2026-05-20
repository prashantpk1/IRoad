"""
mobile_api/helpers/auth.py

JWT authentication helper for Mobile API.

Completely independent from superadmin JWT system.
Uses same PyJWT library but separate signing key,
separate payload structure, and separate TTL settings.

Session revocation layers (defense in depth):
  1. **JTI blacklist** (``mobile:jwt:blacklist:{jti}``) — per access/refresh token.
  2. **Refresh family invalidation** (``mobile:rt:fam_invalid:{rt_fam}``) — revokes
     all JWTs carrying that ``rt_fam`` (access + refresh) until TTL expires.
  3. **``TenantUser.mobile_token_version``** — incremented on password change and
     ``logout-all``; all JWTs with stale ``token_version`` are rejected at auth.

Redis behaviour is controlled via settings (writes with retry; optional strict
blacklist reads). Refresh **one-time consumption** uses ``SET NX``; on Redis
errors, ``MOBILE_API_REFRESH_CONSUME_FAIL_CLOSED_ON_REDIS_ERROR`` (default True)
denies rotation unless disabled. See ``blacklist_token_jti``, ``is_token_blacklisted``,
and ``try_consume_refresh_jti_once``.

Token types:
  access  — short-lived (default 1 hour)
  refresh — long-lived (default 30 days)

Token payload:
  {
    'user_id': '<uuid>',
    'tenant_schema': '<schema_name>',
    'token_type': 'access' | 'refresh',
    'exp': <unix timestamp>,
    'iat': <unix timestamp>,
    'jti': '<uuid>',  # unique token ID for revocation
    'rt_fam': '<uuid>',  # refresh token family (login + rotation chain); optional on legacy JWTs
    'token_version': <int>,  # TenantUser.mobile_token_version
  }

Refresh lifecycle (summary):
  - Each login mints a new ``rt_fam`` and refresh ``jti``.
  - ``POST .../auth/refresh/`` verifies refresh, **consumes** its ``jti`` once in Redis
    (replay / parallel reuse detection), blacklists that ``jti``, then issues a new
    access + refresh pair carrying the **same** ``rt_fam``.
  - Logout blacklists the access ``jti`` and, when the client sends ``refresh_token``,
    blacklists that refresh ``jti``, marks ``rt_fam`` invalidated, and clears the family head key.

Authorization header format:
  Authorization: Bearer <access_token>
"""
import logging
import uuid
import jwt
from datetime import datetime, timezone, timedelta
from django.conf import settings
from django.http import HttpRequest

logger = logging.getLogger('mobile_api')


# ─── Constants ───────────────────────────────────────────────────────────────

TOKEN_TYPE_ACCESS = 'access'
TOKEN_TYPE_REFRESH = 'refresh'
ALGORITHM = 'HS256'


# ─── Signing Key ─────────────────────────────────────────────────────────────

def _get_signing_key() -> str:
    """
    Get JWT signing key from settings.
    Falls back to Django SECRET_KEY if not configured.
    Never returns empty string.
    """
    key = getattr(settings, 'MOBILE_API_JWT_SIGNING_KEY', '').strip()
    if not key:
        key = settings.SECRET_KEY
    return key


def _get_redis_client():
    """Get Redis client if available, else None."""
    try:
        from superadmin.redis_helpers import get_redis_client
        return get_redis_client()
    except Exception:
        return None


def blacklist_token_jti(jti: str, exp_ts: int | None = None) -> bool:
    """
    Blacklist a JWT JTI until its expiry.

    Retries transient Redis errors (``MOBILE_API_BLACKLIST_WRITE_RETRIES``).
    Returns True when persisted, False when Redis is unavailable or all attempts fail.
    """
    if not jti:
        return False
    client = _get_redis_client()
    if client is None:
        logger.warning(
            'mobile.jwt.blacklist_write skipped reason=no_redis jti_prefix=%s',
            jti[:8],
        )
        return False
    if exp_ts:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        ttl = max(60, int(exp_ts) - now_ts)
    else:
        ttl = 3600
    key = f'mobile:jwt:blacklist:{jti}'
    retries = max(
        1,
        int(getattr(settings, 'MOBILE_API_BLACKLIST_WRITE_RETRIES', 2) or 2),
    )
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            client.setex(key, ttl, '1')
            return True
        except Exception as exc:
            last_exc = exc
            continue
    logger.error(
        'mobile.jwt.blacklist_write_failed jti_prefix=%s attempts=%s err=%s',
        jti[:8],
        retries,
        last_exc,
    )
    return False


def is_token_blacklisted(jti: str) -> bool:
    """
    Return True when ``jti`` is present in the blacklist.

    On Redis read errors: returns ``MOBILE_API_JWT_DENY_ON_REDIS_READ_ERROR`` when
    True (fail closed), else False (fail open — token may still be revoked only
    via ``token_version`` / family markers on subsequent checks).
    """
    if not jti:
        return False
    deny_on_error = bool(
        getattr(settings, 'MOBILE_API_JWT_DENY_ON_REDIS_READ_ERROR', False)
    )
    client = _get_redis_client()
    if client is None:
        return deny_on_error
    try:
        return bool(client.get(f'mobile:jwt:blacklist:{jti}'))
    except Exception as exc:
        logger.error(
            'mobile.jwt.blacklist_read_error jti_prefix=%s err=%s',
            jti[:8],
            exc,
        )
        return deny_on_error


# ─── Refresh rotation: one-time use + family head (Redis) ─────────────────────

RT_SPENT_KEY = 'mobile:rt:spent:{jti}'
RT_FAM_HEAD_KEY = 'mobile:rt:fam:{rt_fam}'
RT_FAM_INVALID_KEY = 'mobile:rt:fam_invalid:{rt_fam}'


def mark_refresh_family_invalidated(
    rt_fam: str,
    ttl_seconds: int | None = None,
) -> bool:
    """
    Mark a refresh family as revoked. Any JWT (access or refresh) carrying this
    ``rt_fam`` will fail ``verify_token`` until the key expires.

    Returns True when the key was set in Redis, False if Redis is unavailable
    or the operation failed (callers should still rely on JTI blacklist + version bump).
    """
    fam = (rt_fam or '').strip()
    if not fam:
        return False
    client = _get_redis_client()
    if client is None:
        logger.warning(
            'mobile.rt.fam_invalidate skipped reason=no_redis fam_prefix=%s',
            fam[:8],
        )
        return False
    ttl = int(ttl_seconds or _refresh_ttl_cap_seconds())
    ttl = max(60, min(ttl, _refresh_ttl_cap_seconds()))
    try:
        client.setex(RT_FAM_INVALID_KEY.format(rt_fam=fam), ttl, '1')
        return True
    except Exception as exc:
        logger.error(
            'mobile.rt.fam_invalidate_failed fam_prefix=%s err=%s',
            fam[:8],
            exc,
        )
        return False


def is_refresh_family_invalidated(rt_fam: str) -> bool:
    """True when this ``rt_fam`` has been globally revoked for mobile JWTs."""
    fam = (rt_fam or '').strip()
    if not fam:
        return False
    deny_on_error = bool(
        getattr(settings, 'MOBILE_API_JWT_DENY_ON_REDIS_READ_ERROR', False)
    )
    client = _get_redis_client()
    if client is None:
        return deny_on_error
    try:
        return bool(client.get(RT_FAM_INVALID_KEY.format(rt_fam=fam)))
    except Exception as exc:
        logger.error(
            'mobile.rt.fam_invalid_read_error fam_prefix=%s err=%s',
            fam[:8],
            exc,
        )
        return deny_on_error


def clear_refresh_family_binding(rt_fam: str) -> None:
    """Remove family head key (e.g. on logout)."""
    if not rt_fam:
        return
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.delete(RT_FAM_HEAD_KEY.format(rt_fam=rt_fam))
    except Exception:
        pass


def _refresh_ttl_cap_seconds() -> int:
    return int(
        getattr(settings, 'MOBILE_API_REFRESH_TOKEN_TTL_SECONDS', 2592000) or 2592000
    ) + 600


def _ttl_seconds_until_exp(exp_ts: int | None) -> int:
    """TTL for Redis keys tied to a refresh token's ``exp`` claim."""
    now = int(datetime.now(timezone.utc).timestamp())
    exp = int(exp_ts or (now + 3600))
    return max(60, min(exp - now, _refresh_ttl_cap_seconds()))


def try_consume_refresh_jti_once(jti: str, exp_ts: int | None) -> bool:
    """
    Mark this refresh ``jti`` as consumed exactly once (SET NX).

    Used before issuing rotated tokens. A second presentation of the same
    refresh (replay or lost race) gets ``False``.

    When Redis is unavailable:
    - If ``MOBILE_API_REFRESH_REQUIRE_REDIS`` is True → returns False (fail closed).
    - Else returns True (fail open; rely on blacklist-after-rotation only).

    When Redis returns an error during ``SET``:
    - If ``MOBILE_API_REFRESH_CONSUME_FAIL_CLOSED_ON_REDIS_ERROR`` is True (default),
      returns False so refresh rotation cannot bypass one-time consumption.
    """
    if not jti:
        return False
    client = _get_redis_client()
    require = bool(getattr(settings, 'MOBILE_API_REFRESH_REQUIRE_REDIS', False))
    fail_closed_on_redis_exc = bool(
        getattr(settings, 'MOBILE_API_REFRESH_CONSUME_FAIL_CLOSED_ON_REDIS_ERROR', True),
    )
    if client is None:
        return not require
    ttl = _ttl_seconds_until_exp(exp_ts)
    try:
        return bool(
            client.set(
                RT_SPENT_KEY.format(jti=jti),
                '1',
                nx=True,
                ex=ttl,
            )
        )
    except Exception as exc:
        logger.error(
            'mobile.rt.consume_refresh_redis_error jti_prefix=%s err=%s',
            jti[:8],
            exc,
        )
        if fail_closed_on_redis_exc:
            return False
        return not require


def bind_refresh_family_head(rt_fam: str, refresh_jti: str, refresh_exp_ts: int | None) -> None:
    """
    Store the latest refresh ``jti`` for a family (ops / future bulk revoke).

    Best-effort only; security does not depend on this key.
    """
    if not rt_fam or not refresh_jti:
        return
    client = _get_redis_client()
    if client is None:
        return
    ttl = _ttl_seconds_until_exp(refresh_exp_ts)
    try:
        client.setex(RT_FAM_HEAD_KEY.format(rt_fam=rt_fam), ttl, refresh_jti)
    except Exception:
        pass


# ─── Token Generation ─────────────────────────────────────────────────────────

def generate_access_token(
    user_id: str,
    tenant_schema: str,
    extra_claims: dict | None = None,
) -> str:
    """
    Generate a short-lived access token.

    Args:
        user_id: str UUID of the authenticated user
        tenant_schema: str schema name of the tenant

    Returns:
        Encoded JWT string
    """
    ttl = getattr(
        settings,
        'MOBILE_API_ACCESS_TOKEN_TTL_SECONDS',
        3600,
    )
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': str(user_id),
        'tenant_schema': tenant_schema,
        'token_type': TOKEN_TYPE_ACCESS,
        'iat': int(now.timestamp()),
        'exp': int((now + timedelta(seconds=ttl)).timestamp()),
        'jti': str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    payload.update(_registered_claims_iss_aud())
    return jwt.encode(payload, _get_signing_key(), algorithm=ALGORITHM)


def generate_refresh_token(
    user_id: str,
    tenant_schema: str,
    extra_claims: dict | None = None,
) -> str:
    """
    Generate a long-lived refresh token.

    Args:
        user_id: str UUID of the authenticated user
        tenant_schema: str schema name of the tenant

    Returns:
        Encoded JWT string
    """
    ttl = getattr(
        settings,
        'MOBILE_API_REFRESH_TOKEN_TTL_SECONDS',
        2592000,
    )
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': str(user_id),
        'tenant_schema': tenant_schema,
        'token_type': TOKEN_TYPE_REFRESH,
        'iat': int(now.timestamp()),
        'exp': int((now + timedelta(seconds=ttl)).timestamp()),
        'jti': str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    payload.update(_registered_claims_iss_aud())
    return jwt.encode(payload, _get_signing_key(), algorithm=ALGORITHM)


def _registered_claims_iss_aud() -> dict:
    """Registered JWT iss/aud from settings (mobile API only)."""
    iss = getattr(settings, 'MOBILE_API_JWT_ISS', '') or ''
    aud = getattr(settings, 'MOBILE_API_JWT_AUD', '') or ''
    out = {}
    if (iss or '').strip():
        out['iss'] = str(iss).strip()
    if (aud or '').strip():
        out['aud'] = str(aud).strip()
    return out


def _verify_registered_claims(payload: dict) -> bool:
    """Reject tokens whose iss/aud do not match configured mobile API values."""
    expect_iss = (getattr(settings, 'MOBILE_API_JWT_ISS', '') or '').strip()
    expect_aud = (getattr(settings, 'MOBILE_API_JWT_AUD', '') or '').strip()
    if expect_iss and payload.get('iss') != expect_iss:
        return False
    if expect_aud and payload.get('aud') != expect_aud:
        return False
    return True


def generate_token_pair(
    user_id: str,
    tenant_schema: str,
    extra_claims: dict | None = None,
) -> dict:
    """
    Generate both access and refresh tokens.

    Returns:
        dict with 'access_token', 'refresh_token',
        'access_expires_in', 'refresh_expires_in' (seconds)
    """
    access_ttl = int(
        getattr(settings, 'MOBILE_API_ACCESS_TOKEN_TTL_SECONDS', 3600) or 3600
    )
    refresh_ttl = int(
        getattr(settings, 'MOBILE_API_REFRESH_TOKEN_TTL_SECONDS', 2592000) or 2592000
    )
    return {
        'access_token': generate_access_token(
            user_id,
            tenant_schema,
            extra_claims=extra_claims,
        ),
        'refresh_token': generate_refresh_token(
            user_id,
            tenant_schema,
            extra_claims=extra_claims,
        ),
        'access_expires_in': access_ttl,
        'refresh_expires_in': refresh_ttl,
    }


# ─── Token Verification ───────────────────────────────────────────────────────

def verify_token(token: str, expected_type: str = TOKEN_TYPE_ACCESS) -> dict | None:
    """
    Verify and decode a JWT token.

    Cryptographic and blacklist checks only. Callers that must enforce
    workspace account state (e.g. soft-deleted ``TenantUser``) should
    load the subject after verify — see ``MobileJWTAuthentication`` and
    ``authenticate_request`` / ``authenticate_refresh_request``.

    Args:
        token: JWT string
        expected_type: 'access' or 'refresh'

    Returns:
        Decoded payload dict if valid, None if invalid/expired
    """
    try:
        require_claims = ['exp']
        if bool(getattr(settings, 'MOBILE_API_JWT_REQUIRE_IAT_CLAIM', False)):
            require_claims.append('iat')
        leeway = int(getattr(settings, 'MOBILE_API_JWT_LEEWAY_SECONDS', 0) or 0)
        decode_kwargs: dict = {
            'algorithms': [ALGORITHM],
            'leeway': max(0, leeway),
            'options': {
                'verify_signature': True,
                'verify_exp': True,
                'require': require_claims,
            },
        }
        iss = (getattr(settings, 'MOBILE_API_JWT_ISS', '') or '').strip()
        aud = (getattr(settings, 'MOBILE_API_JWT_AUD', '') or '').strip()
        if iss:
            decode_kwargs['issuer'] = iss
        if aud:
            decode_kwargs['audience'] = aud
        payload = jwt.decode(
            token,
            _get_signing_key(),
            **decode_kwargs,
        )
        # Check token type
        if payload.get('token_type') != expected_type:
            return None
        if not _verify_registered_claims(payload):
            return None
        # Check blacklist (logout revocation)
        if is_token_blacklisted(payload.get('jti', '')):
            return None
        rt_fam = (payload.get('rt_fam') or '').strip()
        if rt_fam and is_refresh_family_invalidated(rt_fam):
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ─── Request Auth Extraction ──────────────────────────────────────────────────

def get_token_from_request(request: HttpRequest) -> str | None:
    """
    Extract Bearer token from Authorization header.

    Returns:
        Token string or None if not present/invalid format
    """
    auth_header = request.headers.get('Authorization', '').strip()
    if auth_header.lower().startswith('bearer '):
        return auth_header.split(' ', 1)[1].strip()
    return None


def authenticate_request(request: HttpRequest) -> dict | None:
    """
    Full authentication flow for a mobile API request.

    Extracts Bearer token from Authorization header,
    verifies it as an access token, returns payload.

    Returns None if there is no token, the token is invalid, or the
    workspace driver session is not valid (same rules as
    ``MobileJWTAuthentication``).
    """
    from mobile_api.helpers.mobile_driver_session import (
        mobile_driver_session_valid_for_programmatic_auth,
    )

    token = get_token_from_request(request)
    if not token:
        return None
    payload = verify_token(token, expected_type=TOKEN_TYPE_ACCESS)
    if payload is None:
        return None
    if not mobile_driver_session_valid_for_programmatic_auth(request, payload):
        return None
    return payload


def authenticate_refresh_request(request: HttpRequest) -> dict | None:
    """
    Authentication flow for token refresh endpoint.

    Same validation surface as access tokens for tenant + driver + user state
    (via ``load_mobile_driver_subject`` rules) but expects a refresh token.
    """
    from mobile_api.helpers.mobile_driver_session import (
        mobile_driver_session_valid_for_programmatic_auth,
    )

    token = get_token_from_request(request)
    if not token:
        return None
    payload = verify_token(token, expected_type=TOKEN_TYPE_REFRESH)
    if payload is None:
        return None
    if not mobile_driver_session_valid_for_programmatic_auth(request, payload):
        return None
    return payload

