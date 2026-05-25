"""
Tenant portal in-app notifications (bell panel).

Phase 1: client contract pre/post expiry and grace alerts for tenant admins,
driven by TenantClientContractSetting.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from tenant_workspace.models import (
    TenantClientContract,
    TenantClientContractSetting,
    TenantInAppNotification,
    TenantUser,
)

TENANT_OWNER_RECIPIENT_KEY = 'owner'
_CONTRACT_CATEGORIES = {
    c.value for c in TenantInAppNotification.Category
}


def resolve_recipient_from_session(*, tenant_id: str, reference_id: str) -> tuple[str, str | None]:
    """
    Return (recipient_key, tenant_user_id or None).
    Tenant-owner portal sessions use reference_id == tenant_id.
    """
    ref = (reference_id or '').strip()
    tid = str(tenant_id or '').strip()
    if not ref or not tid:
        return '', None
    if ref == tid:
        return TENANT_OWNER_RECIPIENT_KEY, None
    return ref, ref


def recipient_is_contract_admin(
    *,
    settings_obj: TenantClientContractSetting,
    recipient_key: str,
    tenant_user_id: str | None,
) -> bool:
    audience = settings_obj.notification_audience
    if audience == TenantClientContractSetting.NotificationAudience.ADMIN_FINANCE:
        if recipient_key == TENANT_OWNER_RECIPIENT_KEY:
            return True
        if not tenant_user_id:
            return False
        role = (
            TenantUser.objects.filter(pk=tenant_user_id)
            .values_list('role_name', flat=True)
            .first()
            or ''
        ).strip().lower()
        return any(
            token in role
            for token in ('admin', 'finance', 'administrator')
        )
    # System Admin (default): tenant owner + administrator roles only.
    if recipient_key == TENANT_OWNER_RECIPIENT_KEY:
        return True
    if not tenant_user_id:
        return False
    role = (
        TenantUser.objects.filter(pk=tenant_user_id)
        .values_list('role_name', flat=True)
        .first()
        or ''
    ).strip().lower()
    return role in ('administrator', 'admin', 'tenant admin', 'system admin')


def _contract_detail_href(contract_id) -> str:
    try:
        return reverse(
            'iroad_tenants:tenant_client_contract_detail',
            kwargs={'contract_id': contract_id},
        )
    except NoReverseMatch:
        return ''


def _contract_specs_for_row(
    contract: TenantClientContract,
    settings_obj: TenantClientContractSetting,
    today,
) -> list[dict]:
    specs: list[dict] = []
    end_date = contract.end_date
    if not end_date:
        return specs

    days_remaining = (end_date - today).days
    client_label = (
        getattr(contract.client_account, 'display_name', None)
        or getattr(contract.client_account, 'account_no', None)
        or 'Client'
    )
    href = _contract_detail_href(contract.contract_id)

    pre_days = int(settings_obj.pre_expiry_notification_days or 0)
    if pre_days > 0 and 0 <= days_remaining <= pre_days:
        specs.append(
            {
                'source_key': f'contract_pre:{contract.contract_id}',
                'category': TenantInAppNotification.Category.CONTRACT_PRE_EXPIRY,
                'title': f'Contract expiring — {contract.contract_no}',
                'message': (
                    f'{client_label}: contract ends {end_date:%Y-%m-%d} '
                    f'({days_remaining} day(s) left).'
                ),
                'href': href,
                'contract': contract,
            }
        )

    post_days = int(settings_obj.post_expiry_notification_days or 0)
    if post_days > 0 and days_remaining < 0:
        days_since = abs(days_remaining)
        if days_since <= post_days:
            specs.append(
                {
                    'source_key': f'contract_post:{contract.contract_id}',
                    'category': TenantInAppNotification.Category.CONTRACT_POST_EXPIRY,
                    'title': f'Contract expired — {contract.contract_no}',
                    'message': (
                        f'{client_label}: contract expired {end_date:%Y-%m-%d} '
                        f'({days_since} day(s) ago).'
                    ),
                    'href': href,
                    'contract': contract,
                }
            )

    if (
        settings_obj.expired_contract_handling_mode
        == TenantClientContractSetting.ExpiredHandling.DEACTIVATE_AFTER_GRACE
    ):
        grace = int(settings_obj.grace_period_days or 0)
        if grace > 0 and days_remaining < 0:
            days_since = abs(days_remaining)
            if days_since <= grace:
                grace_left = grace - days_since
                specs.append(
                    {
                        'source_key': f'contract_grace:{contract.contract_id}',
                        'category': TenantInAppNotification.Category.CONTRACT_GRACE,
                        'title': f'Grace period — {contract.contract_no}',
                        'message': (
                            f'{client_label}: contract in grace period; '
                            f'{grace_left} day(s) before deactivation.'
                        ),
                        'href': href,
                        'contract': contract,
                    }
                )

    return specs


def _should_refresh_existing(
    *,
    frequency: str,
    updated_at,
    today,
) -> bool:
    if not updated_at:
        return True
    updated_date = timezone.localtime(updated_at).date()
    if frequency == TenantClientContractSetting.NotificationFrequency.ONCE:
        return False
    if frequency == TenantClientContractSetting.NotificationFrequency.DAILY:
        return updated_date < today
    if frequency == TenantClientContractSetting.NotificationFrequency.WEEKLY:
        return updated_date < today - timedelta(days=7)
    return False


def _upsert_for_recipient(
    *,
    recipient_key: str,
    tenant_user_id: str | None,
    spec: dict,
    frequency: str,
    today,
) -> None:
    user_fk = None
    if tenant_user_id:
        user_fk = TenantUser.objects.filter(pk=tenant_user_id).first()

    defaults = {
        'recipient_user': user_fk,
        'category': spec['category'],
        'title': spec['title'],
        'message': spec['message'],
        'href': spec.get('href') or '',
        'contract': spec.get('contract'),
        'is_read': False,
        'read_at': None,
    }
    obj, created = TenantInAppNotification.objects.get_or_create(
        recipient_key=recipient_key,
        source_key=spec['source_key'],
        defaults=defaults,
    )
    if created:
        return
    if _should_refresh_existing(
        frequency=frequency,
        updated_at=obj.updated_at,
        today=today,
    ):
        obj.category = spec['category']
        obj.title = spec['title']
        obj.message = spec['message']
        obj.href = spec.get('href') or ''
        obj.contract = spec.get('contract')
        obj.is_read = False
        obj.read_at = None
        obj.save(
            update_fields=[
                'category',
                'title',
                'message',
                'href',
                'contract',
                'is_read',
                'read_at',
                'updated_at',
            ]
        )


def sync_contract_expiry_notifications(
    *,
    recipient_key: str,
    tenant_user_id: str | None = None,
) -> None:
    """Create/update contract alerts for one portal recipient."""
    if not recipient_key:
        return

    settings_obj = TenantClientContractSetting.objects.order_by(
        '-updated_at'
    ).first()
    if settings_obj is None:
        settings_obj = TenantClientContractSetting.objects.create()

    if not recipient_is_contract_admin(
        settings_obj=settings_obj,
        recipient_key=recipient_key,
        tenant_user_id=tenant_user_id,
    ):
        TenantInAppNotification.objects.filter(
            recipient_key=recipient_key,
            category__in=_CONTRACT_CATEGORIES,
        ).delete()
        return

    today = timezone.localdate()
    frequency = settings_obj.notification_frequency
    active_keys: set[str] = set()

    contracts = TenantClientContract.objects.select_related(
        'client_account'
    ).order_by('end_date')
    for contract in contracts:
        for spec in _contract_specs_for_row(contract, settings_obj, today):
            active_keys.add(spec['source_key'])
            _upsert_for_recipient(
                recipient_key=recipient_key,
                tenant_user_id=tenant_user_id,
                spec=spec,
                frequency=frequency,
                today=today,
            )

    stale = TenantInAppNotification.objects.filter(
        recipient_key=recipient_key,
        category__in=_CONTRACT_CATEGORIES,
    )
    if active_keys:
        stale = stale.exclude(source_key__in=active_keys)
    stale.delete()


def sync_all_contract_notification_recipients() -> None:
    """Refresh contract alerts for tenant owner and eligible tenant users."""
    settings_obj = TenantClientContractSetting.objects.order_by(
        '-updated_at'
    ).first()
    if settings_obj is None:
        return

    sync_contract_expiry_notifications(
        recipient_key=TENANT_OWNER_RECIPIENT_KEY,
        tenant_user_id=None,
    )

    user_qs = TenantUser.objects.filter(status=TenantUser.Status.ACTIVE)
    for user in user_qs.iterator():
        sync_contract_expiry_notifications(
            recipient_key=str(user.user_id),
            tenant_user_id=str(user.user_id),
        )


def list_notifications_for_recipient(
    recipient_key: str,
    *,
    limit: int = 50,
) -> list[TenantInAppNotification]:
    if not recipient_key:
        return []
    return list(
        TenantInAppNotification.objects.filter(recipient_key=recipient_key)
        .select_related('contract', 'contract__client_account')
        .order_by('-created_at')[:limit]
    )


def unread_count_for_recipient(recipient_key: str) -> int:
    if not recipient_key:
        return 0
    return TenantInAppNotification.objects.filter(
        recipient_key=recipient_key,
        is_read=False,
    ).count()


def mark_notification_read(*, recipient_key: str, notification_id) -> bool:
    updated = TenantInAppNotification.objects.filter(
        recipient_key=recipient_key,
        pk=notification_id,
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())
    return updated > 0


def mark_all_read(*, recipient_key: str) -> int:
    return TenantInAppNotification.objects.filter(
        recipient_key=recipient_key,
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())


def run_with_tenant_schema(request, callback):
    """Activate tenant workspace schema, run callback, restore public."""
    from iroad_tenants.views import _activate_tenant_workspace_schema

    registry = _activate_tenant_workspace_schema(request)
    if registry is None:
        return None
    try:
        return callback(registry)
    finally:
        connection.set_schema_to_public()
