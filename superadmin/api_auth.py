"""
Tenant **API bridge** authentication (CP-PCS-P1 Type B) — **not** Control Panel admin login.

- ``X-Tenant-ID`` is the subscriber UUID (``TenantProfile`` / master CRM). It scopes
  bridge calls from the **tenant's systems** to shared **master** data (tickets,
  billing APIs, etc.). Queries use ``WHERE tenant_id = …`` (or ``tenant=`` FK) on
  master tables — same URL for all tenants; isolation is logical, not per-host.
- The **API key** authenticates the bridge (maps to that tenant after
  ``check_password``); it is **not** database credentials for the isolated tenant schema.
- **Superadmin** staff sessions must **not** embed subscriber ``tenant_id`` as their
  identity: CP uses ``admin_id`` (see ``redis_helpers.create_admin_session``). When
  the tenant workspace adds JWTs for **human** users after login, include
  ``tenant_id`` (and user id) in those tokens **only** in the tenant domain — keep
  admin and tenant token namespaces separate.

Requires ``X-Tenant-ID`` and optionally ``X-Tenant-API-Key`` (or ``Authorization: Bearer``)
when ``settings.TENANT_API_REQUIRE_KEY`` is True.
"""
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.http import JsonResponse

from .models import TenantProfile


def resolve_tenant_api_request(request):
    """
    Returns (tenant, None) on success, or (None, JsonResponse) on failure.
    """
    tenant_id = (request.headers.get('X-Tenant-ID') or '').strip()
    if not tenant_id:
        return None, JsonResponse(
            {'error': 'Missing X-Tenant-ID header'},
            status=401,
        )

    tenant = TenantProfile.objects.filter(tenant_id=tenant_id).first()
    if not tenant:
        return None, JsonResponse({'error': 'Unknown tenant'}, status=401)
    if tenant.account_status != 'Active':
        return None, JsonResponse(
            {'error': 'Tenant account is not active'},
            status=403,
        )

    require_key = getattr(settings, 'TENANT_API_REQUIRE_KEY', True)
    if not require_key:
        return tenant, None

    if not (tenant.api_bridge_secret_hash or '').strip():
        return None, JsonResponse(
            {
                'error': (
                    'Tenant API key not configured. '
                    'Open Control Panel → Subscriber → generate bridge key.'
                ),
            },
            status=403,
        )

    raw_key = (
        request.headers.get('X-Tenant-API-Key')
        or request.headers.get('X-API-Key')
    )
    if not raw_key and request.headers.get('Authorization', '').startswith(
            'Bearer '):
        raw_key = request.headers.get('Authorization', '').split(' ', 1)[-1].strip()

    if not raw_key:
        return None, JsonResponse(
            {'error': 'Missing API key (X-Tenant-API-Key or Authorization: Bearer)'},
            status=401,
        )

    if not check_password(raw_key, tenant.api_bridge_secret_hash):
        return None, JsonResponse({'error': 'Invalid API key'}, status=403)

    return tenant, None
