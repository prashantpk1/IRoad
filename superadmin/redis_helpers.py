import json
import uuid

import redis
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def get_redis_client():
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def redis_health_check():
    try:
        get_redis_client().ping()
        return True
    except Exception:
        return False


# ─────────────────────────────────────────
# SESSION STORAGE
# ─────────────────────────────────────────

def create_admin_session(admin_user, ip_address, user_agent, timeout_minutes):
    """
    Create Redis session for logged-in **IRoad Control Panel staff** (Super Admin
    / Sales / Support). Payload uses ``admin_id`` only — **no** subscriber
    ``tenant_id`` (tenant UUID is for tenant workspace / API bridge only).

    Returns jti (session ID).
    Key: admin:session:{jti}
    """
    client = get_redis_client()
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
    client.setex(key, ttl_seconds, json.dumps(session_data))
    return jti


def refresh_admin_session(jti, timeout_minutes):
    """
    Refresh TTL and update last_activity on every request.
    Returns True if session exists, False if expired/not found.
    """
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


def get_admin_session(jti):
    """Get session data by JTI. Returns dict or None."""
    client = get_redis_client()
    key = f'admin:session:{jti}'
    data = client.get(key)
    return json.loads(data) if data else None


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

    Returns JTI string (UUID).
    """
    client = get_redis_client()
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
    client.setex(key, ttl_seconds, json.dumps(session_data))
    return token


def refresh_tenant_session(tenant_id, jti, timeout_minutes):
    client = get_redis_client()
    key = f'tenant:{tenant_id}:session:{jti}'
    data = client.get(key)
    if not data:
        return False
    session_data = json.loads(data)
    session_data['last_activity'] = timezone.now().isoformat()
    ttl_seconds = max(60, int(timeout_minutes) * 60)
    client.setex(key, ttl_seconds, json.dumps(session_data))
    return True


def revoke_tenant_session_key(tenant_id, jti):
    """Delete one tenant/driver session from Redis."""
    if not jti:
        return
    client = get_redis_client()
    client.delete(f'tenant:{tenant_id}:session:{jti}')


def revoke_tenant_session_by_jti(jti):
    """
    Delete a tenant/driver session by JTI without prior tenant_id.
    Returns number of deleted keys.
    """
    if not jti:
        return 0
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
    client = get_redis_client()
    key = f'tenant:{tenant_id}:session:{jti}'
    data = client.get(key)
    return json.loads(data) if data else None

