"""Tenant portal subscription access helpers."""

from __future__ import annotations

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

# Path suffixes (no trailing slash) for setup routes — resolve() can fail before
# CommonMiddleware adds a slash, so url_name alone is not enough.
SUBSCRIPTION_SETUP_PATH_SUFFIXES = (
    '/administration/subscription-plan',
    '/administration/subscription-billing',
)


def tenant_has_active_subscription(tenant: TenantProfile) -> bool:
    """
    True when the tenant has a current plan assigned.

    Matches the subscription plan page (``is_current`` / "Current Plan" badge).
    """
    return bool(tenant.current_plan_id)


def is_subscription_setup_request(request) -> bool:
    """Allow subscription/billing setup pages without an active plan."""
    url_name = subscription_setup_url_name(request)
    if url_name in SUBSCRIPTION_SETUP_URL_NAMES:
        return True

    path = (request.path_info or request.path or '').rstrip('/')
    return any(path.endswith(suffix) for suffix in SUBSCRIPTION_SETUP_PATH_SUFFIXES)


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
