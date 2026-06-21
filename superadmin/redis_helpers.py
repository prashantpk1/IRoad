import json
import logging
import threading
import time
import uuid

import redis
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

REDIS_UNAVAILABLE = object()

_redis_pool = None
_redis_pool_lock = threading.Lock()
_redis_unavailable_until = 0.0


def _redis_circuit_seconds():
    return max(5, int(getattr(settings, 'REDIS_CIRCUIT_BREAKER_SECONDS', 30)))


def _redis_connect_timeout():
    return max(1, int(getattr(settings, 'REDIS_SOCKET_CONNECT_TIMEOUT', 2)))


def _redis_socket_timeout():
    return max(1, int(getattr(settings, 'REDIS_SOCKET_TIMEOUT', 5)))


def redis_is_enabled():
    """When False, Redis calls return fallbacks immediately (local dev without Redis)."""
    return bool(getattr(settings, 'REDIS_ENABLED', True))


def is_redis_circuit_open():
    """True when recent Redis failures triggered the circuit breaker."""
    if not redis_is_enabled():
        return True
    return time.monotonic() < _redis_unavailable_until


def open_redis_circuit():
    """Mark Redis unavailable so callers fail fast without socket timeouts."""
    global _redis_unavailable_until
    _redis_unavailable_until = time.monotonic() + _redis_circuit_seconds()


def probe_redis_at_startup():
    """
    Ping Redis once when Django starts. If unreachable, open the circuit breaker
    immediately so the first page load does not wait on connect timeouts.
    """
    if not redis_is_enabled():
        open_redis_circuit()
        logger.info('REDIS_ENABLED is False; Redis session storage skipped.')
        return False
    if redis_health_check():
        logger.debug('Redis startup probe succeeded.')
        return True
    open_redis_circuit()
    logger.warning(
        'Redis is not reachable at %s. Session storage is in degraded mode until '
        'Redis is started (or set REDIS_ENABLED=False in .env for local dev).',
        getattr(settings, 'REDIS_URL', 'redis://127.0.0.1:6379/0'),
    )
    return False


def redis_safe_get(key):
    """Return key value, ``REDIS_UNAVAILABLE`` when Redis is down, else None if missing."""
    if is_redis_circuit_open():
        return REDIS_UNAVAILABLE

    def _get():
        return get_redis_client().get(key)

    _get.__name__ = 'redis_get'
    return _redis_call(_get, fallback=REDIS_UNAVAILABLE)


def redis_safe_setex(key, ttl_seconds, value):
    """Persist a key with TTL. Returns True, False (Redis down), or raises on hard errors."""
    if is_redis_circuit_open():
        return False

    def _setex():
        get_redis_client().setex(key, ttl_seconds, value)
        return True

    _setex.__name__ = 'redis_setex'
    result = _redis_call(_setex, fallback=False)
    return result is True


def redis_safe_set(key, value, *, nx=False, ex=None):
    """SET with optional NX/EX. Returns True/False/None (nx miss), or False when Redis is down."""
    if is_redis_circuit_open():
        return False

    def _set():
        kwargs = {}
        if nx:
            kwargs['nx'] = True
        if ex is not None:
            kwargs['ex'] = ex
        return get_redis_client().set(key, value, **kwargs)

    _set.__name__ = 'redis_set'
    return _redis_call(_set, fallback=False)


def redis_safe_delete(key):
    if is_redis_circuit_open():
        return False

    def _delete():
        get_redis_client().delete(key)
        return True

    _delete.__name__ = 'redis_delete'
    return _redis_call(_delete, fallback=False) is True


def get_redis_client():
    """Return a pooled Redis client (one pool per process)."""
    global _redis_pool
    if _redis_pool is None:
        with _redis_pool_lock:
            if _redis_pool is None:
                _redis_pool = redis.ConnectionPool.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=_redis_connect_timeout(),
                    socket_timeout=_redis_socket_timeout(),
                    retry_on_timeout=True,
                    health_check_interval=30,
                )
    return redis.Redis(connection_pool=_redis_pool)


def reset_redis_client():
    """Drop pooled connections (tests or after Redis restarts)."""
    global _redis_pool, _redis_unavailable_until
    with _redis_pool_lock:
        if _redis_pool is not None:
            try:
                _redis_pool.disconnect(inuse_connections=True)
            except Exception:
                pass
            _redis_pool = None
        _redis_unavailable_until = 0.0


def _redis_call(action, fallback=None):
    """Run a Redis operation; return fallback when Redis is unavailable."""
    global _redis_unavailable_until
    if not redis_is_enabled():
        return fallback
    now = time.monotonic()
    if now < _redis_unavailable_until:
        return fallback
    try:
        result = action()
        _redis_unavailable_until = 0.0
        return result
    except (redis.RedisError, OSError, ConnectionError) as exc:
        _redis_unavailable_until = now + _redis_circuit_seconds()
        logger.warning(
            'Redis unavailable during %s (%s). Retrying after %ss.',
            getattr(action, '__name__', 'redis_op'),
            exc,
            _redis_circuit_seconds(),
        )
        return fallback


def redis_health_check():
    def _ping():
        return get_redis_client().ping()

    _ping.__name__ = 'redis_health_check'
    return _redis_call(_ping, fallback=False) is True


# ─────────────────────────────────────────
# SESSION STORAGE
# ─────────────────────────────────────────

def create_admin_session(admin_user, ip_address, user_agent, timeout_minutes):
    """
    Create Redis session for logged-in **IRoad Control Panel staff** (Super Admin
    / Sales / Support). Payload uses ``admin_id`` only — **no** subscriber
    ``tenant_id`` (tenant UUID is for tenant workspace / API bridge only).

    Returns jti (session ID). When Redis is unavailable the jti is still returned
    so Django session auth can proceed in degraded mode (kill-switch disabled).
    Key: admin:session:{jti}
    """
    jti = str(uuid.uuid4())
    now = timezone.now().isoformat()

    session_data = {
        'jti': jti,
        'admin_id': str(admin_user.id),
        'email': admin_user.email,
        'first_name': admin_user.first_name,
        'last_name': admin_user.last_name,
        'role': admin_user.role.role_name_en if admin_user.role else 'N/A',
        'ip_address': ip_address or '',
        'user_agent': user_agent or '',
        'user_domain': 'Admin',
        'started_at': now,
        'last_activity': now,
    }

    ttl_seconds = timeout_minutes * 60
    key = f'admin:session:{jti}'
    if not redis_safe_setex(key, ttl_seconds, json.dumps(session_data)):
        logger.warning(
            'Redis unavailable; admin session %s not persisted (Django session auth may still work).',
            jti,
        )
    return jti


def refresh_admin_session(jti, timeout_minutes):
    """
    Refresh TTL and update last_activity on every request.
    Returns True if session exists, False if expired/not found, None if Redis is down.
    """
    def _refresh():
        client = get_redis_client()
        key = f'admin:session:{jti}'
        data = client.get(key)
        if not data:
            return False
        session_data = json.loads(data)
        session_data['last_activity'] = timezone.now().isoformat()
        ttl_seconds = timeout_minutes * 60
        client.setex(key, ttl_seconds, json.dumps(session_data))
        return True

    _refresh.__name__ = 'refresh_admin_session'
    return _redis_call(_refresh, fallback=None)


def get_admin_session(jti):
    """Get session data by JTI. Returns dict or None."""
    def _fetch():
        client = get_redis_client()
        key = f'admin:session:{jti}'
        data = client.get(key)
        return json.loads(data) if data else None

    _fetch.__name__ = 'get_admin_session'
    return _redis_call(_fetch, fallback=None)


def revoke_admin_session(jti):
    """Delete specific session from Redis (logout or kill)."""
    client = get_redis_client()
    client.delete(f'admin:session:{jti}')


def revoke_all_sessions_for_admin(admin_id):
    """
    Revoke ALL active sessions for a specific admin.
    Used when admin is suspended — Kill Switch.
    Uses Redis SCAN to find all matching keys safely.
    """
    client = get_redis_client()
    pattern = 'admin:session:*'
    pipeline = client.pipeline()

    cursor = 0
    while True:
        cursor, keys = client.scan(cursor, match=pattern, count=100)
        for key in keys:
            data = client.get(key)
            if data:
                session = json.loads(data)
                if session.get('admin_id') == str(admin_id):
                    pipeline.delete(key)
        if cursor == 0:
            break

    pipeline.execute()


def get_all_active_admin_sessions():
    """
    Return list of all active admin sessions.
    Used by Active Sessions Monitor (FRM-CP-11-03).
    """
    client = get_redis_client()
    pattern = 'admin:session:*'
    sessions = []

    cursor = 0
    while True:
        cursor, keys = client.scan(cursor, match=pattern, count=100)
        for key in keys:
            data = client.get(key)
            if data:
                session = json.loads(data)
                ttl = client.ttl(key)
                session['ttl_seconds'] = ttl
                sessions.append(session)
        if cursor == 0:
            break

    sessions.sort(key=lambda x: x.get('started_at', ''), reverse=True)
    return sessions


def count_active_admin_sessions():
    """Count active admin sessions from Redis efficiently."""
    client = get_redis_client()
    pattern = 'admin:session:*'
    count = 0
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor, match=pattern, count=1000)
        count += len(keys)
        if cursor == 0:
            break
    return count


# ─────────────────────────────────────────
# TENANT KILL SWITCH (Phase 8 ready)
# ─────────────────────────────────────────

def revoke_all_tenant_sessions(tenant_id):
    """
    Kill Switch: Destroy all sessions for a Tenant.
    Keys: tenant:{tenant_id}:session:{j}
    Populated by create_tenant_session() or tenant workspace on login.
    """
    client = get_redis_client()
    pattern = f'tenant:{tenant_id}:session:*'
    deleted = 0

    cursor = 0
    while True:
        pipeline = client.pipeline()
        batch_has_keys = False
        cursor, keys = client.scan(cursor, match=pattern, count=100)
        for key in keys:
            pipeline.delete(key)
            batch_has_keys = True
        if batch_has_keys:
            # Sum actual delete results (1 when key deleted, 0 otherwise).
            deleted += sum(int(v or 0) for v in pipeline.execute())
        if cursor == 0:
            break

    return deleted


def create_tenant_session(
        tenant_id,
        user_domain,
        reference_id,
        reference_name,
        ip_address,
        user_agent,
        timeout_minutes,
        jti=None):
    """
    Register a **tenant** web user or driver session in Redis (Kill Switch).
    Payload **includes** ``tenant_id`` so revokes and monitoring are scoped to
    the subscriber. Do not use this shape for CP admin sessions — use
    ``create_admin_session`` instead.

    If the tenant app issues JWTs after login, carry the same subscriber UUID
    in claims (e.g. ``tenant_id``) for this domain only — never mix into admin
    tokens.

    Returns JTI string (UUID). When Redis is unavailable the jti is still returned
    so tenant portal JWT/cookie auth can proceed in degraded mode.
    """
    token = jti or str(uuid.uuid4())
    now = timezone.now().isoformat()
    session_data = {
        'jti': token,
        'tenant_id': str(tenant_id),
        'user_domain': user_domain,
        'reference_id': str(reference_id),
        'reference_name': reference_name or '',
        'ip_address': ip_address or '',
        'user_agent': (user_agent or '')[:500],
        'started_at': now,
        'last_activity': now,
    }
    ttl_seconds = max(60, int(timeout_minutes) * 60)
    key = f'tenant:{tenant_id}:session:{token}'
    if not redis_safe_setex(key, ttl_seconds, json.dumps(session_data)):
        logger.warning(
            'Redis unavailable; tenant session %s not persisted (JWT/cookie auth may still work).',
            token,
        )
    return token


def refresh_tenant_session(tenant_id, jti, timeout_minutes):
    status, _data = refresh_and_get_tenant_session(tenant_id, jti, timeout_minutes)
    return status


def refresh_and_get_tenant_session(tenant_id, jti, timeout_minutes):
    """
    Refresh TTL and return session payload in one Redis round trip.

    Returns ``(status, session_data)`` where *status* is:
    - ``True`` — session found and refreshed
    - ``False`` — session missing / expired
    - ``None`` — Redis unavailable (caller may fall back to JWT)
    """

    def _refresh():
        client = get_redis_client()
        key = f'tenant:{tenant_id}:session:{jti}'
        data = client.get(key)
        if not data:
            return (False, None)
        session_data = json.loads(data)
        session_data['last_activity'] = timezone.now().isoformat()
        ttl_seconds = max(60, int(timeout_minutes) * 60)
        client.setex(key, ttl_seconds, json.dumps(session_data))
        return (True, session_data)

    _refresh.__name__ = 'refresh_and_get_tenant_session'
    result = _redis_call(_refresh, fallback=(None, None))
    if result is None:
        return (None, None)
    return result


def revoke_tenant_session_key(tenant_id, jti):
    """Delete one tenant/driver session from Redis (best-effort when Redis is down)."""
    if not jti:
        return False
    key = f'tenant:{tenant_id}:session:{jti}'
    return redis_safe_delete(key)


def revoke_tenant_session_by_jti(jti):
    """
    Delete a tenant/driver session by JTI without prior tenant_id.
    Returns number of deleted keys.
    """
    if not jti:
        return 0

    def _revoke():
        client = get_redis_client()
        pattern = f'tenant:*:session:{jti}'
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=pattern, count=100)
            for key in keys:
                deleted += client.delete(key)
            if cursor == 0:
                break
        return deleted

    _revoke.__name__ = 'revoke_tenant_session_by_jti'
    result = _redis_call(_revoke, fallback=0)
    return int(result or 0)


def revoke_tenant_workspace_sessions_for_user_reference(tenant_id, tenant_user_pk):
    """
    Best-effort: revoke tenant **portal** Redis sessions for a workspace ``TenantUser``.

    Matches ``tenant_id`` + ``reference_id`` (``TenantUser`` PK) and
    ``user_domain`` ``Tenant_User`` (sub-admin / tenant user web sessions).

    Does not enumerate mobile JWTs (those are invalidated via blacklist / DB checks).
    """
    if not tenant_id or not tenant_user_pk:
        return 0
    tid = str(tenant_id).strip()
    ref = str(tenant_user_pk).strip()
    try:
        sessions = get_all_active_tenant_sessions()
    except Exception:
        return 0
    total = 0
    for sess in sessions:
        if str(sess.get('tenant_id') or '').strip() != tid:
            continue
        if str(sess.get('reference_id') or '').strip() != ref:
            continue
        if (sess.get('user_domain') or '').strip() != 'Tenant_User':
            continue
        jti = sess.get('jti')
        if jti:
            total += int(revoke_tenant_session_by_jti(jti) or 0)
    return total


def get_all_active_tenant_sessions():
    """
    Return list of all active tenant web/driver sessions from Redis.
    Keys: tenant:{tenant_id}:session:{jti}
    """
    client = get_redis_client()
    pattern = 'tenant:*:session:*'
    sessions = []

    cursor = 0
    while True:
        cursor, keys = client.scan(cursor, match=pattern, count=200)
        for key in keys:
            data = client.get(key)
            if not data:
                continue
            session = json.loads(data)
            ttl = client.ttl(key)
            session['ttl_seconds'] = ttl
            sessions.append(session)
        if cursor == 0:
            break

    sessions.sort(key=lambda x: x.get('started_at', ''), reverse=True)
    return sessions


def get_tenant_session(tenant_id, jti):
    """Get one tenant session payload by tenant id + jti."""
    if not tenant_id or not jti:
        return None

    def _fetch():
        client = get_redis_client()
        key = f'tenant:{tenant_id}:session:{jti}'
        data = client.get(key)
        return json.loads(data) if data else None

    _fetch.__name__ = 'get_tenant_session'
    return _redis_call(_fetch, fallback=None)


_TENANT_SESSION_REQUEST_CACHE_ATTR = '_iroad_tenant_session_cache'


def stash_tenant_session_on_request(request, tenant_id, jti, session_data):
    """Cache tenant session on the request to avoid duplicate Redis reads per page."""
    if request is None:
        return
    setattr(
        request,
        _TENANT_SESSION_REQUEST_CACHE_ATTR,
        {
            'tenant_id': str(tenant_id or '').strip(),
            'jti': str(jti or '').strip(),
            'data': session_data,
        },
    )


def get_tenant_session_for_request(request, tenant_id, jti):
    """
    Return tenant session data, reusing a per-request cache when available.
    Falls back to ``get_tenant_session`` (circuit-breaker aware).
    """
    if not tenant_id or not jti:
        return None
    tid = str(tenant_id).strip()
    token = str(jti).strip()
    if request is not None:
        cached = getattr(request, _TENANT_SESSION_REQUEST_CACHE_ATTR, None)
        if (
            isinstance(cached, dict)
            and cached.get('tenant_id') == tid
            and cached.get('jti') == token
        ):
            return cached.get('data')
    data = get_tenant_session(tid, token)
    stash_tenant_session_on_request(request, tid, token, data)
    return data
