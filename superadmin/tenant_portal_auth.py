from django.conf import settings
from django.core import signing


TENANT_PORTAL_COOKIE_NAME = 'iroad_tenant_auth'
TENANT_PORTAL_COOKIE_SALT = 'iroad.tenant.portal.auth'
TENANT_PORTAL_JWT_COOKIE_NAME = 'iroad_tenant_jwt'


def _tenant_cookie_name_for_id(tenant_id):
    safe = ''.join(ch for ch in str(tenant_id or '') if ch.isalnum())
    return f'{TENANT_PORTAL_COOKIE_NAME}_{safe}' if safe else TENANT_PORTAL_COOKIE_NAME


def _tenant_jwt_cookie_name_for_id(tenant_id):
    safe = ''.join(ch for ch in str(tenant_id or '') if ch.isalnum())
    return f'{TENANT_PORTAL_JWT_COOKIE_NAME}_{safe}' if safe else TENANT_PORTAL_JWT_COOKIE_NAME


def _extract_requested_tid(request):
    return str(
        request.GET.get('tid')
        or request.POST.get('tid')
        or ''
    ).strip()


def _load_cookie_payload(raw):
    if not raw:
        return None
    try:
        data = signing.loads(raw, salt=TENANT_PORTAL_COOKIE_SALT)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict):
        return None
    return data


def get_tenant_portal_cookie_payload(request):
    from .tenant_jwt import verify_tenant_access_jwt

    requested_tid = _extract_requested_tid(request)

    # Optional: Bearer token (e.g. mobile / API clients).
    auth_header = (request.META.get('HTTP_AUTHORIZATION') or '').strip()
    if auth_header.lower().startswith('bearer '):
        bearer = auth_header.split(' ', 1)[1].strip()
        bearer_claims = verify_tenant_access_jwt(bearer)
        if bearer_claims:
            tenant_id = str(bearer_claims.get('tenant_id') or '').strip()
            jti = str(bearer_claims.get('jti') or '').strip()
            if tenant_id and jti:
                if not requested_tid or tenant_id == requested_tid:
                    return {
                        'tenant_id': tenant_id,
                        'jti': jti,
                        'jwt_claims': bearer_claims,
                    }

    # Prefer HttpOnly JWT cookies (post-login); no tid query param required.
    jwt_claims = None
    if requested_tid:
        raw_scoped_jwt = request.COOKIES.get(_tenant_jwt_cookie_name_for_id(requested_tid), '').strip()
        if raw_scoped_jwt:
            jwt_claims = verify_tenant_access_jwt(raw_scoped_jwt)
            if jwt_claims and str(jwt_claims.get('tenant_id') or '').strip() != requested_tid:
                jwt_claims = None
    if jwt_claims is None:
        raw_jwt = request.COOKIES.get(TENANT_PORTAL_JWT_COOKIE_NAME, '').strip()
        if raw_jwt:
            jwt_claims = verify_tenant_access_jwt(raw_jwt)
            if jwt_claims and requested_tid:
                if str(jwt_claims.get('tenant_id') or '').strip() != requested_tid:
                    jwt_claims = None
    if jwt_claims:
        tenant_id = str(jwt_claims.get('tenant_id') or '').strip()
        jti = str(jwt_claims.get('jti') or '').strip()
        if tenant_id and jti:
            return {'tenant_id': tenant_id, 'jti': jti, 'jwt_claims': jwt_claims}

    if requested_tid:
        raw_scoped = request.COOKIES.get(_tenant_cookie_name_for_id(requested_tid), '')
        scoped = _load_cookie_payload(raw_scoped)
        if isinstance(scoped, dict):
            tenant_id = str(scoped.get('tenant_id') or '').strip()
            jti = str(scoped.get('jti') or '').strip()
            if tenant_id and jti and tenant_id == requested_tid:
                return {'tenant_id': tenant_id, 'jti': jti}

    raw = request.COOKIES.get(TENANT_PORTAL_COOKIE_NAME, '')
    data = _load_cookie_payload(raw)
    if not data:
        return None

    # New format supports multiple tenant sessions in one browser profile.
    sessions = data.get('sessions')
    if isinstance(sessions, dict):
        current_tid = str(data.get('current_tenant_id') or '').strip()
        tenant_id = requested_tid or current_tid
        if not tenant_id:
            return None
        jti = str(sessions.get(tenant_id) or '').strip()
        if not jti:
            return None
        return {
            'tenant_id': tenant_id,
            'jti': jti,
        }

    # Legacy format fallback.
    tenant_id = str(data.get('tenant_id') or '').strip()
    jti = str(data.get('jti') or '').strip()
    if not tenant_id or not jti:
        return None
    return {'tenant_id': tenant_id, 'jti': jti}


def set_tenant_portal_cookie(response, tenant_id, jti, request=None, access_jwt=None):
    tenant_id = str(tenant_id).strip()
    jti = str(jti).strip()
    sessions = {}
    if request is not None:
        existing = _load_cookie_payload(request.COOKIES.get(TENANT_PORTAL_COOKIE_NAME, '')) or {}
        if isinstance(existing.get('sessions'), dict):
            sessions = {
                str(k).strip(): str(v).strip()
                for k, v in existing.get('sessions', {}).items()
                if str(k).strip() and str(v).strip()
            }
        else:
            old_tid = str(existing.get('tenant_id') or '').strip()
            old_jti = str(existing.get('jti') or '').strip()
            if old_tid and old_jti:
                sessions[old_tid] = old_jti

    sessions[tenant_id] = jti
    payload = {
        'v': 2,
        'current_tenant_id': tenant_id,
        'sessions': sessions,
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
    scoped_payload = {'tenant_id': tenant_id, 'jti': jti}
    scoped_value = signing.dumps(scoped_payload, salt=TENANT_PORTAL_COOKIE_SALT)
    response.set_cookie(
        _tenant_cookie_name_for_id(tenant_id),
        scoped_value,
        max_age=int(getattr(settings, 'SESSION_COOKIE_AGE', 86400)),
        httponly=True,
        secure=bool(getattr(settings, 'SESSION_COOKIE_SECURE', False)),
        samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
        path='/',
    )
    cookie_max_age = int(getattr(settings, 'SESSION_COOKIE_AGE', 86400))
    jwt_raw = (access_jwt or '').strip()
    if jwt_raw:
        response.set_cookie(
            TENANT_PORTAL_JWT_COOKIE_NAME,
            jwt_raw,
            max_age=cookie_max_age,
            httponly=True,
            secure=bool(getattr(settings, 'SESSION_COOKIE_SECURE', False)),
            samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
            path='/',
        )
        response.set_cookie(
            _tenant_jwt_cookie_name_for_id(tenant_id),
            jwt_raw,
            max_age=cookie_max_age,
            httponly=True,
            secure=bool(getattr(settings, 'SESSION_COOKIE_SECURE', False)),
            samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
            path='/',
        )
    return response


def clear_tenant_portal_cookie(response, request=None):
    target_tid = ''
    if request is not None:
        auth = get_tenant_portal_cookie_payload(request) or {}
        target_tid = str(auth.get('tenant_id') or _extract_requested_tid(request) or '').strip()

    if target_tid and request is not None:
        # Remove only the target tenant from shared cookie map.
        existing = _load_cookie_payload(request.COOKIES.get(TENANT_PORTAL_COOKIE_NAME, '')) or {}
        sessions = existing.get('sessions')
        if isinstance(sessions, dict):
            sessions = {
                str(k).strip(): str(v).strip()
                for k, v in sessions.items()
                if str(k).strip() and str(v).strip() and str(k).strip() != target_tid
            }
            payload = {
                'v': 2,
                'current_tenant_id': next(iter(sessions.keys()), ''),
                'sessions': sessions,
            }
            if sessions:
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
            else:
                response.delete_cookie(
                    TENANT_PORTAL_COOKIE_NAME,
                    path='/',
                    samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
                )
                response.delete_cookie(
                    TENANT_PORTAL_JWT_COOKIE_NAME,
                    path='/',
                    samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
                )
        else:
            response.delete_cookie(
                TENANT_PORTAL_COOKIE_NAME,
                path='/',
                samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
            )
            response.delete_cookie(
                TENANT_PORTAL_JWT_COOKIE_NAME,
                path='/',
                samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
            )

        response.delete_cookie(
            _tenant_cookie_name_for_id(target_tid),
            path='/',
            samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
        )
        response.delete_cookie(
            _tenant_jwt_cookie_name_for_id(target_tid),
            path='/',
            samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
        )
        return response

    response.delete_cookie(
        TENANT_PORTAL_COOKIE_NAME,
        path='/',
        samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
    )
    response.delete_cookie(
        TENANT_PORTAL_JWT_COOKIE_NAME,
        path='/',
        samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
    )
    return response
