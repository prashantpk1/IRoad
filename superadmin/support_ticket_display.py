"""
Display helpers for ``SupportTicket`` rows stored in the public schema.
"""
import os
import uuid

from django.db import connection
from django.utils import timezone
from django.utils.translation import gettext as _

from iroad_tenants.models import TenantRegistry
from tenant_workspace.models import TenantUser

from .models import AdminUser, Role


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
        role = ''
        role_id = getattr(admin_user, 'role_id', None)
        if role_id:
            role = (
                Role.objects.filter(pk=role_id)
                .values_list('role_name_en', flat=True)
                .first()
                or ''
            ).strip()
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


def format_support_ticket_datetime(value):
    """Format datetimes for tenant ticket detail UI (e.g. 2026-04-07 | 10:00:15 AM)."""
    if not value:
        return '-'
    local_dt = timezone.localtime(value)
    return local_dt.strftime('%Y-%m-%d | %I:%M:%S %p')


def support_ticket_priority_tone(priority):
    """Return a CSS color token for priority emphasis."""
    token = (priority or '').strip().lower()
    if token in {'critical', 'high'}:
        return '#ef4444'
    if token == 'medium':
        return '#f59e0b'
    return '#64748b'


def _resolve_tenant_user_label_map(tenant_pk, sender_ids):
    labels = {}
    if not sender_ids:
        return labels
    previous_tenant = connection.tenant
    connection.set_schema_to_public()
    try:
        reg = TenantRegistry.objects.filter(tenant_profile_id=tenant_pk).first()
        if not reg:
            return labels
        connection.set_tenant(reg)
        for tu in TenantUser.all_objects.filter(user_id__in=sender_ids).only(
            'user_id', 'full_name', 'username', 'email',
        ):
            username = (
                (tu.full_name or '').strip()
                or (tu.username or '').strip()
                or (tu.email or '').strip()
            )
            if username:
                labels[str(tu.user_id)] = username
    finally:
        if isinstance(previous_tenant, TenantRegistry):
            connection.set_tenant(previous_tenant)
        else:
            connection.set_schema_to_public()
    return labels


def support_ticket_reply_display_map(ticket, replies):
    """
    Map each reply PK to display metadata for the tenant conversation UI.

    Tenant messages use grey styling; support/admin messages use green label +
    blue accent; system messages use support styling.
    """
    items = list(replies)
    if not items:
        return {}

    tenant_pk = str(ticket.tenant_id)
    tenant_sender_ids = {
        (reply.sender_id or '').strip()
        for reply in items
        if reply.sender_type == 'Tenant_User' and (reply.sender_id or '').strip()
    }
    admin_sender_ids = {
        (reply.sender_id or '').strip()
        for reply in items
        if reply.sender_type == 'Admin_Support' and (reply.sender_id or '').strip()
    }

    tenant_labels = _resolve_tenant_user_label_map(tenant_pk, tenant_sender_ids)
    admin_labels = {}
    if admin_sender_ids:
        for admin in AdminUser.objects.filter(pk__in=admin_sender_ids).only(
            'id', 'first_name', 'last_name', 'email',
        ):
            username, _admin_role = _admin_user_username_and_role(admin)
            if username and username != '-':
                admin_labels[str(admin.pk)] = username

    out = {}
    for reply in items:
        sender_id = (reply.sender_id or '').strip()
        if reply.sender_type == 'Tenant_User':
            sender_name = tenant_labels.get(sender_id) or str(_('Tenant User'))
            sender_label = sender_name.upper()
            sender_kind = 'tenant'
        elif reply.sender_type == 'Admin_Support':
            sender_name = admin_labels.get(sender_id) or str(_('Support Team'))
            sender_label = f"{sender_name.upper()} ({str(_('SUPPORT TEAM')).upper()})"
            sender_kind = 'support'
        else:
            sender_label = str(_('SUPPORT TEAM')).upper()
            sender_kind = 'support'
        out[reply.pk] = {
            'sender_label': sender_label,
            'sender_kind': sender_kind,
            'timestamp_display': format_support_ticket_datetime(reply.created_at),
        }
    return out


def support_ticket_attachment_rows(replies):
    """Non-internal reply attachments for the Attachments tab."""
    rows = []
    for reply in replies:
        attachment = getattr(reply, 'attachment', None)
        if not attachment:
            continue
        rows.append({
            'reply_id': reply.reply_id,
            'filename': os.path.basename(attachment.name),
            'url': attachment.url,
            'uploaded_at': format_support_ticket_datetime(reply.created_at),
        })
    return rows


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
    previous_tenant = connection.tenant
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
        if isinstance(previous_tenant, TenantRegistry):
            connection.set_tenant(previous_tenant)
        else:
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
    admin_ids = {raw for _ticket_pk, raw in need_admin}
    if admin_ids:
        for a in AdminUser.objects.filter(pk__in=admin_ids).only(
            'id', 'first_name', 'last_name', 'email', 'is_root', 'role_id',
        ):
            username, role = _admin_user_username_and_role(a)
            admin_map[str(a.pk)] = {'username': username, 'role': role}

    for pk, raw in need_admin:
        out[pk] = admin_map.get(
            raw,
            {'username': str(_('Unknown user')), 'role': '-'},
        )

    return out
