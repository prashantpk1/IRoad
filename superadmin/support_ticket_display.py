"""
Display helpers for ``SupportTicket`` rows stored in the public schema.
"""
import uuid

from django.db import connection
from django.utils.translation import gettext as _

from iroad_tenants.models import TenantRegistry
from tenant_workspace.models import TenantUser

from .models import AdminUser


def _admin_user_username_and_role(admin_user):
    """Login id (email) and control-panel role label for an ``AdminUser``."""
    if admin_user is None:
        return '-', '-'
    username = (admin_user.email or '').strip()
    if not username:
        username = f'{admin_user.first_name or ""} {admin_user.last_name or ""}'.strip()
    if getattr(admin_user, 'is_root', False):
        role = str(_('Super Admin'))
    else:
        role_obj = getattr(admin_user, 'role', None)
        role = (getattr(role_obj, 'role_name_en', None) or '').strip() if role_obj else ''
    return username or '-', role or '-'


def support_ticket_assignee_display_parts(ticket):
    """Assignee username + role for tenant list/detail (superadmin assignee)."""
    assignee = getattr(ticket, 'assigned_to', None)
    if assignee is None:
        return {'username': '-', 'role': '-'}
    username, role = _admin_user_username_and_role(assignee)
    return {'username': username, 'role': role}


def support_ticket_assignee_display(ticket):
    """Single-line assignee label (name · role)."""
    parts = support_ticket_assignee_display_parts(ticket)
    if parts['username'] == '-' and parts['role'] == '-':
        return '-'
    if parts['role'] and parts['role'] != '-':
        return f"{parts['username']} · {parts['role']}"
    return parts['username']


def support_ticket_created_by_display_map(tickets):
    """
    Map each ticket's primary key to ``{'username': ..., 'role': ...}`` for Created By.

    ``SupportTicket.created_by`` may hold a tenant workspace ``TenantUser`` id,
    a ``TenantProfile`` id (session fallback), a control-panel ``AdminUser`` id,
    or a short non-UUID label.
    """
    items = list(tickets)
    if not items:
        return {}

    by_tenant_ids = {}
    for t in items:
        raw = (t.created_by or '').strip()
        if raw:
            by_tenant_ids.setdefault(str(t.tenant_id), set()).add(raw)

    tenant_user_labels = {}
    connection.set_schema_to_public()
    try:
        tenant_pks = list(by_tenant_ids.keys())
        regs = {
            str(r.tenant_profile_id): r
            for r in TenantRegistry.objects.filter(
                tenant_profile_id__in=tenant_pks,
            ).select_related('tenant_profile')
        }
        for tenant_pk, ids in by_tenant_ids.items():
            reg = regs.get(tenant_pk)
            if not reg:
                continue
            connection.set_tenant(reg)
            for tu in TenantUser.all_objects.filter(user_id__in=ids).only(
                'user_id', 'full_name', 'username', 'email', 'role_name',
            ):
                username = (
                    (tu.username or '').strip()
                    or (tu.email or '').strip()
                    or (tu.full_name or '').strip()
                )
                if username:
                    role = (tu.role_name or '').strip() or str(_('Tenant User'))
                    tenant_user_labels[(tenant_pk, str(tu.user_id))] = {
                        'username': username,
                        'role': role,
                    }
    finally:
        connection.set_schema_to_public()

    out = {}
    tenant_by = {}
    for t in items:
        tp = getattr(t, 'tenant', None)
        if tp is not None:
            tenant_by[str(t.tenant_id)] = tp

    need_admin = []
    for t in items:
        raw = (t.created_by or '').strip()
        tenant_pk = str(t.tenant_id)
        if not raw:
            out[t.pk] = {'username': '-', 'role': '-'}
            continue
        pair = (tenant_pk, raw)
        if pair in tenant_user_labels:
            out[t.pk] = tenant_user_labels[pair]
            continue
        if raw == tenant_pk:
            tp = tenant_by.get(tenant_pk)
            cn = (tp.company_name or '').strip() if tp else ''
            out[t.pk] = {
                'username': cn or str(_('Tenant portal')),
                'role': str(_('Tenant Admin')),
            }
            continue
        try:
            uuid.UUID(raw)
        except (ValueError, TypeError, AttributeError):
            out[t.pk] = {'username': raw, 'role': '-'}
            continue
        need_admin.append((t.pk, raw))

    admin_map = {}
    admin_ids = {raw for _, raw in need_admin}
    if admin_ids:
        for a in AdminUser.objects.filter(pk__in=admin_ids).select_related('role').only(
            'id', 'first_name', 'last_name', 'email', 'is_root', 'role__role_name_en',
        ):
            username, role = _admin_user_username_and_role(a)
            admin_map[str(a.pk)] = {'username': username, 'role': role}

    for pk, raw in need_admin:
        out[pk] = admin_map.get(
            raw,
            {'username': str(_('Unknown user')), 'role': '-'},
        )

    return out
