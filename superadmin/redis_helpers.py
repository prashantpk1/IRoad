import json
import uuid

import jwt
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
    Create Redis session for logged-in admin.
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


# ─────────────────────────────────────────
# TENANT KILL SWITCH (Phase 8 ready)
# ─────────────────────────────────────────

def revoke_all_tenant_sessions(tenant_id):
    """
    Kill Switch: Destroy all sessions for a Tenant.
    Phase 8: tenant session keys will follow pattern:
    tenant:{tenant_id}:session:{jti}
    This function is ready — keys will be populated in Phase 8.
    """
    client = get_redis_client()
    pattern = f'tenant:{tenant_id}:session:*'
    pipeline = client.pipeline()

    cursor = 0
    while True:
        cursor, keys = client.scan(cursor, match=pattern, count=100)
        for key in keys:
            pipeline.delete(key)
        if cursor == 0:
            break

    pipeline.execute()

