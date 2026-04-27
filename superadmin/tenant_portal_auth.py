from django.conf import settings
from django.core import signing


TENANT_PORTAL_COOKIE_NAME = 'iroad_tenant_auth'
TENANT_PORTAL_COOKIE_SALT = 'iroad.tenant.portal.auth'


def get_tenant_portal_cookie_payload(request):
    raw = request.COOKIES.get(TENANT_PORTAL_COOKIE_NAME, '')
    if not raw:
        return None
    try:
        data = signing.loads(raw, salt=TENANT_PORTAL_COOKIE_SALT)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict):
        return None
    tenant_id = str(data.get('tenant_id') or '').strip()
    jti = str(data.get('jti') or '').strip()
    if not tenant_id or not jti:
        return None
    return {
        'tenant_id': tenant_id,
        'jti': jti,
    }


def set_tenant_portal_cookie(response, tenant_id, jti):
    payload = {
        'tenant_id': str(tenant_id),
        'jti': str(jti),
    }
    value = signing.dumps(payload, salt=TENANT_PORTAL_COOKIE_SALT)
    response.set_cookie(
        TENANT_PORTAL_COOKIE_NAME,
        value,
        max_age=int(getattr(settings, 'SESSION_COOKIE_AGE', 86400)),
        httponly=True,
        secure=bool(getattr(settings, 'SESSION_COOKIE_SECURE', False)),
        samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
        path='/',
    )
    return response


def clear_tenant_portal_cookie(response):
    response.delete_cookie(
        TENANT_PORTAL_COOKIE_NAME,
        path='/',
        samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
    )
    return response
