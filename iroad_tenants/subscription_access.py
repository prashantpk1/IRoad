"""Tenant portal subscription access helpers."""

from __future__ import annotations

from django.utils import timezone

from superadmin.models import TenantProfile

# Tenant owner / tenant-admin sessions may access these routes without an active plan.
SUBSCRIPTION_SETUP_URL_NAMES = frozenset(
    {
        'tenant_subscription_plan',
        'tenant_subscription_billing',
        'tenant_invoice_download',
        'tenant_invoice_export_all',
        'tenant_logout',
        'tenant_my_account',
    }
)


def tenant_has_active_subscription(tenant: TenantProfile) -> bool:
    """True when the subscriber has a current plan that has not expired."""
    if not tenant.current_plan_id:
        return False
    expiry = tenant.subscription_expiry_date
    if expiry is None:
        return True
    return expiry >= timezone.now().date()


def tenant_portal_is_owner_admin(session_data: dict, tenant: TenantProfile) -> bool:
    """Tenant portal owner login (not a workspace sub-user)."""
    reference_id = str((session_data or {}).get('reference_id') or '').strip()
    return not reference_id or reference_id == str(tenant.tenant_id)


def subscription_setup_url_name(request) -> str | None:
    from django.urls import resolve

    try:
        match = resolve(request.path_info)
    except Exception:
        return None
    return getattr(match, 'url_name', None)
