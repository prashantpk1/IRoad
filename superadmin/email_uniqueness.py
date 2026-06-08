"""Cross-domain email checks between Control Panel admins and tenant subscribers.

An email blocks reuse on the other side only when the owning record is:
  - not soft-deleted (``is_deleted=False``), and
  - actively enabled (admin ``status='Active'`` / tenant ``account_status='Active'``).

Deactivated or soft-deleted records do not block cross-domain email reuse.

An active super admin email always blocks tenant subscriber email assignment,
regardless of the tenant account status. Super admin email is only blocked by
an active tenant when the admin account itself is Active.
"""

from __future__ import annotations

ACTIVE_ADMIN_STATUS = 'Active'
ACTIVE_TENANT_STATUS = 'Active'


def normalize_email(value: str) -> str:
    return (value or '').strip().lower()


def is_admin_email_blocking(admin) -> bool:
    if admin is None:
        return False
    return (
        not getattr(admin, 'is_deleted', False)
        and getattr(admin, 'status', '') == ACTIVE_ADMIN_STATUS
    )


def is_tenant_email_blocking(tenant) -> bool:
    if tenant is None:
        return False
    return (
        not getattr(tenant, 'is_deleted', False)
        and getattr(tenant, 'account_status', '') == ACTIVE_TENANT_STATUS
    )


def active_tenant_email_conflict(email: str, *, exclude_tenant_pk=None) -> bool:
    from superadmin.models import TenantProfile

    normalized = normalize_email(email)
    if not normalized:
        return False
    qs = TenantProfile.objects.filter(
        primary_email__iexact=normalized,
        account_status=ACTIVE_TENANT_STATUS,
        is_deleted=False,
    )
    if exclude_tenant_pk:
        qs = qs.exclude(pk=exclude_tenant_pk)
    return qs.exists()


def active_admin_email_conflict(email: str, *, exclude_admin_pk=None) -> bool:
    from superadmin.models import AdminUser

    normalized = normalize_email(email)
    if not normalized:
        return False
    qs = AdminUser.objects.filter(
        email__iexact=normalized,
        status=ACTIVE_ADMIN_STATUS,
        is_deleted=False,
    )
    if exclude_admin_pk:
        qs = qs.exclude(pk=exclude_admin_pk)
    return qs.exists()


def admin_activation_email_blocked(admin) -> str | None:
    """Return an error message when an admin cannot be activated with its email."""
    if not is_admin_email_blocking(admin):
        return None
    if active_tenant_email_conflict(admin.email):
        return 'This email is already used by an active tenant admin.'
    return None


def tenant_activation_email_blocked(tenant) -> str | None:
    """Return an error message when a tenant cannot be activated with its email."""
    if not is_tenant_email_blocking(tenant):
        return None
    if active_admin_email_conflict(tenant.primary_email):
        return 'This email is already used by an active super admin.'
    return None
