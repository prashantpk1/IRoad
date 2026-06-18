from django.utils import timezone
from django.conf import settings

from superadmin.redis_helpers import get_tenant_session_for_request
from superadmin.tenant_portal_auth import get_tenant_portal_cookie_payload
from iroad_tenants.tenant_dashboard_search import build_dashboard_search_routes
from iroad_tenants.tenant_notifications import (
    list_notifications_for_recipient,
    resolve_recipient_from_session,
    sync_contract_expiry_notifications,
    unread_count_for_recipient,
)
from superadmin.models import SystemBanner
from iroad_tenants.tenant_system_config import (
    resolve_tenant_system_config,
    tenant_system_config_for_js,
)


def tenant_system_configuration(request):
    """Expose organization system configuration to tenant portal templates."""
    path = (getattr(request, 'path', '') or '').lower()
    if not path.startswith('/tenant/'):
        return {
            'tenant_system_config': {},
            'tenant_system_config_js': {},
        }

    config = resolve_tenant_system_config(request)
    return {
        'tenant_system_config': config,
        'tenant_system_config_js': tenant_system_config_for_js(config),
    }


def tenant_system_banners(request):
    """
    Provide active/non-expired global banners to tenant-facing templates.
    """
    path = (getattr(request, 'path', '') or '').lower()
    if not path.startswith('/tenant/'):
        return {'tenant_system_banners': []}

    now = timezone.now()
    banners = SystemBanner.objects.filter(
        is_active=True,
        valid_from__lte=now,
    ).filter(
        valid_until__isnull=True,
    ) | SystemBanner.objects.filter(
        is_active=True,
        valid_from__lte=now,
        valid_until__gt=now,
    )
    banners = banners.order_by('-valid_from')
    return {'tenant_system_banners': list(banners[:5])}


def tenant_web_push_config(request):
    """Expose tenant web-push config to tenant portal templates."""
    path = (getattr(request, 'path', '') or '').lower()
    if not path.startswith('/tenant/'):
        return {'tenant_web_push_config': {}}

    cfg = {
        'apiKey': (getattr(settings, 'FIREBASE_WEB_API_KEY', '') or '').strip(),
        'authDomain': (getattr(settings, 'FIREBASE_WEB_AUTH_DOMAIN', '') or '').strip(),
        'projectId': (getattr(settings, 'FIREBASE_WEB_PROJECT_ID', '') or '').strip(),
        'storageBucket': (getattr(settings, 'FIREBASE_WEB_STORAGE_BUCKET', '') or '').strip(),
        'messagingSenderId': (getattr(settings, 'FIREBASE_WEB_MESSAGING_SENDER_ID', '') or '').strip(),
        'appId': (getattr(settings, 'FIREBASE_WEB_APP_ID', '') or '').strip(),
        'vapidKey': (getattr(settings, 'FCM_WEB_VAPID_KEY', '') or '').strip(),
    }
    return {'tenant_web_push_config': cfg}


def tenant_in_app_notifications(request):
    """Bell panel items for tenant owner / admin users (contract expiry alerts)."""
    path = (getattr(request, 'path', '') or '').lower()
    if not path.startswith('/tenant/'):
        return {
            'tenant_notification_items': [],
            'tenant_notification_unread_count': 0,
        }

    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = auth_payload.get('tenant_id')
    tenant_jti = auth_payload.get('jti')
    if not tenant_id or not tenant_jti:
        return {
            'tenant_notification_items': [],
            'tenant_notification_unread_count': 0,
        }

    session_data = get_tenant_session_for_request(
        request,
        str(tenant_id),
        str(tenant_jti),
    ) or {}
    reference_id = str(session_data.get('reference_id') or '').strip()
    recipient_key, tenant_user_id = resolve_recipient_from_session(
        tenant_id=str(tenant_id),
        reference_id=reference_id,
    )
    if not recipient_key:
        return {
            'tenant_notification_items': [],
            'tenant_notification_unread_count': 0,
        }

    from iroad_tenants.tenant_notifications import run_with_tenant_schema

    def _load(_registry):
        sync_contract_expiry_notifications(
            recipient_key=recipient_key,
            tenant_user_id=tenant_user_id,
        )
        items = list_notifications_for_recipient(recipient_key)
        return {
            'tenant_notification_items': items,
            'tenant_notification_unread_count': unread_count_for_recipient(
                recipient_key
            ),
        }

    payload = run_with_tenant_schema(request, _load)
    if payload is None:
        return {
            'tenant_notification_items': [],
            'tenant_notification_unread_count': 0,
        }
    return payload


def tenant_dashboard_search_routes(request):
    """Search API + list URLs for navbar global search on tenant pages."""
    path = (getattr(request, 'path', '') or '').lower()
    if not path.startswith('/tenant/'):
        return {
            'tenant_dashboard_search_routes': {},
            'dashboard_search_routes': {},
            'tenant_search_results_url': '',
        }
    routes = build_dashboard_search_routes()
    return {
        'tenant_dashboard_search_routes': routes,
        'dashboard_search_routes': routes,
        'tenant_search_results_url': routes.get('results', ''),
    }
