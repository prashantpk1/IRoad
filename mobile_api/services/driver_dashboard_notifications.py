"""
mobile_api/services/driver_dashboard_notifications.py

Lightweight notification summary for the driver home dashboard.

Summary-only: capped item projections, aggregate counts, FCM readiness metadata.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from mobile_api.helpers.dashboard_request_cache import resolve_tenant_profile_id
from mobile_api.helpers.dashboard_notifications import (
    CATEGORY_ASSIGNMENT,
    CATEGORY_CRITICAL,
    CATEGORY_OPERATIONAL_WARNING,
    map_push_event_to_category,
    severity_for_category,
)


def _items_limit(variant: str = 'full') -> int:
    if variant == 'summary':
        return int(
            getattr(settings, 'MOBILE_API_DASHBOARD_NOTIFICATION_SUMMARY_ITEMS_LIMIT', 5)
            or 5
        )
    return int(
        getattr(settings, 'MOBILE_API_DASHBOARD_NOTIFICATION_ITEMS_LIMIT', 8) or 8
    )


def _push_lookback_days() -> int:
    return int(
        getattr(settings, 'MOBILE_API_DASHBOARD_NOTIFICATIONS_PUSH_LOOKBACK_DAYS', 14)
        or 14
    )


def _use_push_receipts() -> bool:
    return bool(
        getattr(settings, 'MOBILE_API_DASHBOARD_NOTIFICATIONS_USE_PUSH_RECEIPTS', True)
    )


def _iso_dt(value) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace('+00:00', 'Z')


_INBOX_ONLY = (
    'notification_id',
    'category',
    'severity',
    'source',
    'title',
    'body',
    'is_read',
    'event_code',
    'shipment_id',
    'movement_id',
    'created_at',
)


def build_fcm_context(
    *,
    driver,
    tenant_schema: str,
    request=None,
    tenant_profile_id: str | None = None,
) -> dict[str, Any]:
    """FCM integration metadata (no send — registration state only)."""
    driver_id = str(getattr(driver, 'driver_id', driver.pk))
    device_registered = False
    push_enabled = bool((getattr(settings, 'FCM_SERVER_KEY', '') or '').strip())

    if push_enabled and tenant_schema:
        try:
            from superadmin.models import PushDeviceToken

            profile_id = resolve_tenant_profile_id(
                tenant_schema,
                request=request,
                prefetched=tenant_profile_id,
            )
            if profile_id is not None:
                device_registered = PushDeviceToken.objects.filter(
                    tenant_id=profile_id,
                    user_domain='Driver',
                    reference_id=driver_id,
                    is_active=True,
                ).exists()
        except Exception:
            device_registered = False

    return {
        'push_enabled': push_enabled,
        'device_token_registered': device_registered,
        'channel': 'fcm',
        'inbox_deep_link': '/driver/notifications',
        'register_token_route': '/api/tenant/push/token/',
    }


def project_inbox_row(row, *, request=None) -> dict[str, Any]:
    """Map ``DriverMobileNotification`` model row to API projection."""
    category = row.category or 'general'
    return {
        'id': str(row.notification_id),
        'category': category,
        'severity': row.severity or severity_for_category(category),
        'source': row.source or 'system',
        'title': row.title or '',
        'body': (row.body or '').strip(),
        'is_read': bool(row.is_read),
        'event_code': row.event_code or None,
        'shipment_id': str(row.shipment_id) if row.shipment_id else None,
        'movement_id': str(row.movement_id) if row.movement_id else None,
        'created_at': _iso_dt(row.created_at),
        'deep_link': _deep_link_for_category(category, row),
    }


def _deep_link_for_category(category: str, row) -> str:
    if row.shipment_id:
        return f'/driver/shipments/{row.shipment_id}'
    if category == CATEGORY_ASSIGNMENT:
        return '/driver/assignments'
    if category == CATEGORY_OPERATIONAL_WARNING:
        return '/driver/operations'
    if category == CATEGORY_CRITICAL:
        return '/driver/alerts'
    return '/driver/notifications'


def project_ephemeral_row(
    *,
    ephemeral_id: str,
    category: str,
    title: str,
    body: str = '',
    event_code: str | None = None,
    shipment_id: str | None = None,
) -> dict[str, Any]:
    """Synthetic summary item (not persisted)."""
    return {
        'id': ephemeral_id,
        'category': category,
        'severity': severity_for_category(category),
        'source': 'operational',
        'title': title,
        'body': body,
        'is_read': False,
        'event_code': event_code,
        'shipment_id': shipment_id,
        'movement_id': None,
        'created_at': _iso_dt(timezone.now()),
        'deep_link': '/driver/operations' if not shipment_id else f'/driver/shipments/{shipment_id}',
        'ephemeral': True,
    }


def build_ephemeral_operational_warnings(
    *,
    counters: dict[str, int] | None,
    welcome_ctx=None,
    current_job: dict[str, Any] | None,
    request=None,
) -> list[dict[str, Any]]:
    """Derive live operational warnings from dashboard snapshots (no DB write)."""
    counters = counters or {}
    items: list[dict[str, Any]] = []
    pending_pod = int(counters.get('pending_pod') or 0)
    cod_pending = int(counters.get('cod_pending') or 0)

    if welcome_ctx is not None:
        if getattr(welcome_ctx, 'driver_assignment_required', False) and not getattr(
            welcome_ctx, 'truck', None
        ):
            items.append(
                project_ephemeral_row(
                    ephemeral_id='eph:assignment_required',
                    category=CATEGORY_ASSIGNMENT,
                    title=str(_('mobile.dashboard.notification.assignment_required')),
                    body=str(_('mobile.dashboard.notification.assignment_required_body')),
                    event_code='ASSIGNMENT_REQUIRED',
                )
            )
        elif not getattr(welcome_ctx, 'assignment', None) and int(
            counters.get('active_shipments') or 0
        ) > 0:
            items.append(
                project_ephemeral_row(
                    ephemeral_id='eph:no_truck_assignment',
                    category=CATEGORY_ASSIGNMENT,
                    title=str(_('mobile.dashboard.notification.no_truck')),
                    event_code='NO_TRUCK',
                )
            )

    if pending_pod > 0:
        shipment_id = None
        if current_job and current_job.get('has_active_job'):
            shipment_id = current_job.get('shipment_id')
        items.append(
            project_ephemeral_row(
                ephemeral_id='eph:pending_pod',
                category=CATEGORY_OPERATIONAL_WARNING,
                title=str(_('mobile.dashboard.notification.pending_pod')),
                body=str(_('mobile.dashboard.notification.pending_pod_body')) % {
                    'count': pending_pod,
                },
                event_code='POD_PENDING',
                shipment_id=shipment_id,
            )
        )

    if cod_pending > 0:
        shipment_id = None
        if current_job and current_job.get('has_active_job'):
            shipment_id = current_job.get('shipment_id')
        items.append(
            project_ephemeral_row(
                ephemeral_id='eph:cod_pending',
                category=CATEGORY_OPERATIONAL_WARNING,
                title=str(_('mobile.dashboard.notification.cod_pending')),
                body=str(_('mobile.dashboard.notification.cod_pending_body')) % {
                    'count': cod_pending,
                },
                event_code='COD_PENDING',
                shipment_id=shipment_id,
            )
        )

    return items


def aggregate_inbox_counts(driver) -> dict[str, int]:
    """Single aggregate query on tenant ``DriverMobileNotification``."""
    from mobile_api.helpers.dashboard_security import inbox_queryset_for_driver

    base = inbox_queryset_for_driver(driver)
    unread_qs = base.filter(is_read=False)

    agg = unread_qs.aggregate(
        unread_count=Count('pk'),
        critical_count=Count(
            'pk',
            filter=Q(category=CATEGORY_CRITICAL),
        ),
        assignment_count=Count(
            'pk',
            filter=Q(category=CATEGORY_ASSIGNMENT),
        ),
        operational_warnings_count=Count(
            'pk',
            filter=Q(category=CATEGORY_OPERATIONAL_WARNING),
        ),
    )
    return {k: int(agg.get(k) or 0) for k in agg}


def fetch_inbox_item_projections(
    *,
    driver,
    limit: int,
) -> list[dict[str, Any]]:
    from mobile_api.helpers.dashboard_security import inbox_queryset_for_driver

    rows = (
        inbox_queryset_for_driver(driver)
        .order_by('-created_at')[:limit]
    )
    return [project_inbox_row(r) for r in rows]


def fetch_push_receipt_projections(
    *,
    driver,
    tenant_schema: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Recent FCM push receipts for this driver (public schema, read as unread)."""
    if not _use_push_receipts():
        return []

    tenant_profile_id = _resolve_tenant_profile_id(tenant_schema)
    if tenant_profile_id is None:
        return []

    try:
        from superadmin.models import PushNotificationReceipt
    except Exception:
        return []

    since = timezone.now() - timedelta(days=_push_lookback_days())
    driver_id = str(driver.driver_id)
    rows = (
        PushNotificationReceipt.objects.filter(
            tenant_id=tenant_profile_id,
            user_domain='Driver',
            reference_id=driver_id,
            created_at__gte=since,
            delivery_status='Sent',
        )
        .order_by('-created_at')[:limit]
    )

    items: list[dict[str, Any]] = []
    for row in rows:
        category = map_push_event_to_category(row.event_code)
        items.append(
            {
                'id': f'push:{row.receipt_id}',
                'category': category,
                'severity': severity_for_category(category),
                'source': 'fcm',
                'title': (row.title or '').strip() or str(_('mobile.dashboard.notification.push')),
                'body': (row.message or '').strip(),
                'is_read': True,
                'event_code': row.event_code or None,
                'shipment_id': None,
                'movement_id': None,
                'created_at': _iso_dt(row.created_at),
                'deep_link': row.action_link or '/driver/notifications',
                'ephemeral': False,
                'push_receipt': True,
                'push_receipt_id': str(row.receipt_id),
            }
        )
    return items


def merge_summary_items(
    *,
    persisted: list[dict[str, Any]],
    push_rows: list[dict[str, Any]],
    ephemeral: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Merge sources, dedupe by id, sort by created_at desc, cap."""
    combined = persisted + push_rows + ephemeral
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in combined:
        rid = str(row.get('id') or '')
        if rid:
            if rid in seen:
                continue
            seen.add(rid)
        deduped.append(row)
    deduped.sort(key=lambda r: r.get('created_at') or '', reverse=True)
    return deduped[:limit]


def build_notifications_summary(
    *,
    driver,
    tenant_schema: str,
    request=None,
    counters: dict[str, int] | None = None,
    welcome_ctx=None,
    current_job: dict[str, Any] | None = None,
    variant: str = 'full',
    tenant_profile_id: str | None = None,
) -> dict[str, Any]:
    """
    Dashboard ``notifications_summary`` block.
    """
    limit = _items_limit(variant)
    db_counts = aggregate_inbox_counts(driver)
    ephemeral = build_ephemeral_operational_warnings(
        counters=counters,
        welcome_ctx=welcome_ctx,
        current_job=current_job,
        request=request,
    )

    ephemeral_critical = sum(
        1 for e in ephemeral if e.get('category') == CATEGORY_CRITICAL
    )
    ephemeral_assignment = sum(
        1 for e in ephemeral if e.get('category') == CATEGORY_ASSIGNMENT
    )
    ephemeral_operational = sum(
        1 for e in ephemeral if e.get('category') == CATEGORY_OPERATIONAL_WARNING
    )

    if tenant_profile_id is None and welcome_ctx is not None:
        tenant_profile_id = getattr(welcome_ctx, 'tenant_profile_id', None)

    push_rows = fetch_push_receipt_projections(
        driver=driver,
        tenant_schema=tenant_schema,
        limit=limit,
        request=request,
        tenant_profile_id=tenant_profile_id,
    )
    push_recent_count = len(push_rows)

    persisted = fetch_inbox_item_projections(driver=driver, limit=limit)
    items = merge_summary_items(
        persisted=persisted,
        push_rows=push_rows,
        ephemeral=ephemeral,
        limit=limit,
    )

    unread_count = int(db_counts['unread_count'])
    critical_count = db_counts['critical_count'] + ephemeral_critical
    assignment_count = db_counts['assignment_count'] + ephemeral_assignment
    operational_warnings_count = (
        db_counts['operational_warnings_count'] + ephemeral_operational
    )

    return {
        'unread_count': unread_count,
        'push_recent_count': push_recent_count,
        'ephemeral_hint_count': len(ephemeral),
        'critical_count': critical_count,
        'assignment_count': assignment_count,
        'operational_warnings_count': operational_warnings_count,
        'items': items,
        'fcm': build_fcm_context(
            driver=driver,
            tenant_schema=tenant_schema,
            request=request,
            tenant_profile_id=tenant_profile_id,
        ),
    }


def get_driver_notifications_summary(
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    jwt_payload: dict | None = None,
    variant: str = 'full',
) -> dict[str, Any]:
    """``GET /driver/dashboard/notifications-summary/`` service entry."""
    import logging

    from django_tenants.utils import schema_context

    from mobile_api.serializers.driver_dashboard_notifications import (
        DashboardNotificationsSummarySerializer,
    )
    from mobile_api.helpers.dashboard_security import resolve_secure_dashboard_context

    logger = logging.getLogger('mobile_api')
    secured = resolve_secure_dashboard_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        request=request,
        jwt_payload=jwt_payload,
    )
    if not secured['success']:
        return {'success': False, 'error': secured['error']}

    driver = secured['ctx'].driver
    tenant_schema = secured['ctx'].tenant_schema
    driver_id = str(driver.driver_id)

    from mobile_api.helpers.dashboard_cache import cache_get, cache_set
    from mobile_api.helpers.dashboard_observability import dashboard_timer

    cached = cache_get(
        tenant_schema=tenant_schema,
        driver_id=driver_id,
        slice_name='notifications',
        extra=variant,
    )
    if cached is not None:
        return {'success': True, 'notifications_summary': cached}

    try:
        with dashboard_timer(
            operation='get_driver_notifications_summary',
            tenant_schema=tenant_schema,
            driver_id=driver_id,
        ):
            with schema_context(tenant_schema):
                from mobile_api.helpers.dashboard_ownership import (
                    preload_driver_ownership_scope,
                )
                from mobile_api.helpers.dashboard_security import (
                    sanitize_notification_items,
                )

                ownership = preload_driver_ownership_scope(driver)
                summary = build_notifications_summary(
                    driver=driver,
                    tenant_schema=tenant_schema,
                    request=request,
                    variant=variant,
                )
                if summary.get('items'):
                    summary = dict(summary)
                    summary['items'] = sanitize_notification_items(
                        items=list(summary['items']),
                        scope=ownership,
                    )
                data = DashboardNotificationsSummarySerializer(instance=summary).data
                cache_set(
                    tenant_schema=tenant_schema,
                    driver_id=driver_id,
                    slice_name='notifications',
                    data=data,
                    extra=variant,
                )
    except Exception as exc:
        logger.exception(
            'get_driver_notifications_summary failed schema=%s: %s',
            tenant_schema,
            exc,
        )
        return {'success': False, 'error': _('mobile.validation.failed')}

    return {'success': True, 'notifications_summary': data}
