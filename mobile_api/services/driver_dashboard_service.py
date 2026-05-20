"""
mobile_api/services/driver_dashboard_service.py

Driver home dashboard — lightweight, driver-scoped aggregates for mobile landing.

All ORM access runs inside ``schema_context(tenant_schema)``. No portal list
queries, no full timelines, no cross-tenant scans.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _
from django_tenants.utils import schema_context

from mobile_api.services.driver_dashboard_current_job import (
    build_current_job_snapshot,
    fetch_latest_active_shipment,
    project_truck_summary,
)
from mobile_api.services.driver_dashboard_quick_actions import (
    build_dashboard_quick_actions,
    build_quick_actions_meta,
)
from mobile_api.services.driver_dashboard_notifications import (
    build_notifications_summary,
)
from mobile_api.services.driver_dashboard_build import DashboardBuildState
from mobile_api.services.driver_dashboard_recent_activity import build_recent_activity
from mobile_api.serializers.driver_dashboard import serialize_dashboard_payload
from mobile_api.services.driver_dashboard_context import load_driver_welcome_context
from mobile_api.services.driver_dashboard_counters import build_dashboard_counters
from mobile_api.services.driver_dashboard_welcome import build_dashboard_welcome
from mobile_api.helpers.dashboard_cache import cache_get, cache_set
from mobile_api.helpers.dashboard_observability import dashboard_timer
from mobile_api.helpers.dashboard_ownership import preload_driver_ownership_scope
from mobile_api.helpers.dashboard_security import (
    resolve_secure_dashboard_context,
    sanitize_dashboard_payload,
)

logger = logging.getLogger('mobile_api')

DashboardVariant = Literal['full', 'summary']


@dataclass(frozen=True)
class DashboardBuildOptions:
    """Controls section depth for full vs summary endpoints."""

    variant: DashboardVariant = 'full'
    recent_activity_limit: int | None = None

    def resolved_recent_limit(self) -> int:
        if self.recent_activity_limit is not None:
            return max(0, int(self.recent_activity_limit))
        if self.variant == 'summary':
            return int(
                getattr(
                    settings,
                    'MOBILE_API_DASHBOARD_SUMMARY_RECENT_ACTIVITY_LIMIT',
                    5,
                )
                or 5
            )
        return int(
            getattr(settings, 'MOBILE_API_DASHBOARD_RECENT_ACTIVITY_LIMIT', 10)
            or 10
        )


def _iso_timestamp() -> str:
    return timezone.now().isoformat().replace('+00:00', 'Z')


def build_driver_summary(
    *,
    driver,
    tenant_user,
    shell,
) -> dict[str, Any]:
    """Compact identity + contact block for dashboard modules."""
    assignment = shell.assignment
    return {
        'driver_id': str(driver.driver_id),
        'driver_code': driver.driver_code,
        'name': shell.name,
        'profile_photo_url': shell.profile_photo_url,
        'driver_status': driver.driver_status,
        'driver_type': str(driver.driver_type or ''),
        'mobile_number': driver.mobile_number or '',
        'whatsapp_number': driver.whatsapp_number or '',
        'email': getattr(tenant_user, 'email', '') or '',
        'full_name': getattr(tenant_user, 'full_name', '') or '',
        'username': getattr(tenant_user, 'username', '') or '',
        'role_name': getattr(tenant_user, 'role_name', '') or '',
        'user_status': getattr(tenant_user, 'status', '') or '',
        'tenant_id': shell.tenant_id,
        'schema_name': shell.schema_name,
        'organization_name': shell.organization_name,
        'assigned_truck': project_truck_summary(shell.truck),
        'assignment_status': (
            assignment.assignment_status if assignment else None
        ),
    }


def build_dashboard_timestamps(*, request=None) -> dict[str, str]:
    from mobile_api.helpers.i18n import get_request_language

    return {
        'generated_at': _iso_timestamp(),
        'timezone': getattr(settings, 'TIME_ZONE', 'UTC'),
        'locale': get_request_language(request) if request is not None else '',
    }


def build_dashboard_payload(
    *,
    driver,
    tenant_user,
    tenant_schema: str,
    request=None,
    options: DashboardBuildOptions | None = None,
    ownership_scope=None,
) -> dict[str, Any]:
    """
    Assemble all dashboard sections (unserialized dict tree).
    """
    opts = options or DashboardBuildOptions()
    ownership = ownership_scope or preload_driver_ownership_scope(driver)
    build_state = DashboardBuildState(
        driver=driver,
        tenant_schema=tenant_schema,
        request=request,
        variant=opts.variant,
    )
    welcome_ctx = load_driver_welcome_context(
        driver=driver,
        tenant_user=tenant_user,
        tenant_schema=tenant_schema,
        request=request,
    )
    build_state.tenant_profile_id = welcome_ctx.tenant_profile_id
    timestamps = build_dashboard_timestamps(request=request)
    counters = build_dashboard_counters(driver=driver)
    welcome = build_dashboard_welcome(
        driver=driver,
        tenant_user=tenant_user,
        ctx=welcome_ctx,
        request=request,
        counters=counters,
    )
    driver_summary = build_driver_summary(
        driver=driver,
        tenant_user=tenant_user,
        shell=welcome_ctx,
    )
    latest_shipment = build_state.get_latest_active_shipment(
        fetcher=fetch_latest_active_shipment,
    )
    current_job = build_current_job_snapshot(
        driver=driver,
        request=request,
        latest_shipment=latest_shipment,
        build_state=build_state,
    )
    quick_actions = build_dashboard_quick_actions(
        counters=counters,
        current_job=current_job,
        request=request,
        driver=driver,
        ownership_scope=ownership,
    )
    quick_actions_meta = build_quick_actions_meta(actions=quick_actions)
    notifications_summary = build_notifications_summary(
        driver=driver,
        tenant_schema=tenant_schema,
        request=request,
        counters=counters,
        welcome_ctx=welcome_ctx,
        current_job=current_job,
        variant=opts.variant,
        tenant_profile_id=build_state.tenant_profile_id,
    )
    recent_activity = build_recent_activity(
        driver=driver,
        request=request,
        limit=opts.resolved_recent_limit(),
        variant=opts.variant,
        build_state=build_state,
        inject_shipment_row=latest_shipment,
    )

    return {
        'variant': opts.variant,
        'welcome': welcome,
        'driver_summary': driver_summary,
        'counters': counters,
        'current_job': current_job,
        'quick_actions': quick_actions,
        'quick_actions_meta': quick_actions_meta,
        'notifications_summary': notifications_summary,
        'recent_activity': recent_activity,
        'timestamps': timestamps,
        'generated_at': timestamps['generated_at'],
    }


def _serialize_current_job(snapshot: dict[str, Any], *, request=None) -> dict[str, Any]:
    from mobile_api.serializers.driver_dashboard import DashboardCurrentJobSerializer

    if getattr(settings, 'MOBILE_API_DASHBOARD_FAST_SERIALIZE', True):
        return snapshot
    return DashboardCurrentJobSerializer(instance=snapshot, context={'request': request}).data


def _serialize_quick_actions(
    actions: list[dict[str, Any]],
    meta: dict[str, Any],
    *,
    request=None,
) -> dict[str, Any]:
    from mobile_api.serializers.driver_dashboard_quick_actions import (
        DashboardQuickActionSerializer,
    )
    from mobile_api.serializers.driver_dashboard import DashboardQuickActionsMetaSerializer

    if getattr(settings, 'MOBILE_API_DASHBOARD_FAST_SERIALIZE', True):
        return {'quick_actions': actions, 'quick_actions_meta': meta}
    return {
        'quick_actions': DashboardQuickActionSerializer(
            instance=actions,
            many=True,
            context={'request': request},
        ).data,
        'quick_actions_meta': DashboardQuickActionsMetaSerializer(instance=meta).data,
    }


def _fetch_dashboard_for_user(
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    jwt_payload: dict | None = None,
    options: DashboardBuildOptions,
    log_label: str,
) -> dict[str, Any]:
    secured = resolve_secure_dashboard_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        request=request,
        jwt_payload=jwt_payload,
    )
    if not secured['success']:
        return {'success': False, 'error': secured['error']}

    sec_ctx = secured['ctx']
    driver = sec_ctx.driver
    tenant_user = sec_ctx.tenant_user
    tenant_schema = sec_ctx.tenant_schema
    driver_id = str(driver.driver_id)
    variant = options.variant

    slice_name = 'summary' if variant == 'summary' else 'full'
    cached = cache_get(
        tenant_schema=tenant_schema,
        driver_id=driver_id,
        slice_name=slice_name,
    )
    if cached is not None:
        return {'success': True, 'dashboard': cached}

    try:
        with dashboard_timer(
            operation=log_label,
            tenant_schema=tenant_schema,
            driver_id=driver_id,
        ):
            with schema_context(tenant_schema):
                ownership = preload_driver_ownership_scope(driver)
                payload = build_dashboard_payload(
                    driver=driver,
                    tenant_user=tenant_user,
                    tenant_schema=tenant_schema,
                    request=request,
                    options=options,
                    ownership_scope=ownership,
                )
                payload = sanitize_dashboard_payload(
                    driver=driver,
                    payload=payload,
                    ownership_scope=ownership,
                )
                data = serialize_dashboard_payload(
                    payload,
                    request=request,
                )
                cache_set(
                    tenant_schema=tenant_schema,
                    driver_id=driver_id,
                    slice_name=slice_name,
                    data=data,
                )
    except Exception as exc:
        logger.exception(
            '%s failed schema=%s user_id=%s: %s',
            log_label,
            tenant_schema,
            user_id,
            exc,
        )
        return {'success': False, 'error': _('mobile.validation.failed')}

    return {'success': True, 'dashboard': data}


def get_driver_dashboard(
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    jwt_payload: dict | None = None,
) -> dict[str, Any]:
    """``GET /api/v1/mobile/driver/dashboard/`` — full dashboard."""
    return _fetch_dashboard_for_user(
        user_id=user_id,
        tenant_schema=tenant_schema,
        request=request,
        jwt_payload=jwt_payload,
        options=DashboardBuildOptions(variant='full'),
        log_label='get_driver_dashboard',
    )


def get_driver_dashboard_summary(
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    jwt_payload: dict | None = None,
) -> dict[str, Any]:
    """
    ``GET /api/v1/mobile/driver/dashboard/summary/`` — same contract, tuned for
    frequent refresh (smaller recent-activity cap).
    """
    return _fetch_dashboard_for_user(
        user_id=user_id,
        tenant_schema=tenant_schema,
        request=request,
        jwt_payload=jwt_payload,
        options=DashboardBuildOptions(variant='summary'),
        log_label='get_driver_dashboard_summary',
    )


def get_driver_dashboard_current_job(
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    jwt_payload: dict | None = None,
) -> dict[str, Any]:
    """``GET /api/v1/mobile/driver/dashboard/current-job/`` — lightweight poll."""
    secured = resolve_secure_dashboard_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        request=request,
        jwt_payload=jwt_payload,
    )
    if not secured['success']:
        return {'success': False, 'error': secured['error']}

    sec_ctx = secured['ctx']
    driver = sec_ctx.driver
    tenant_schema = sec_ctx.tenant_schema
    driver_id = str(driver.driver_id)

    cached = cache_get(
        tenant_schema=tenant_schema,
        driver_id=driver_id,
        slice_name='current_job',
    )
    if cached is not None:
        return {'success': True, 'current_job': cached}

    try:
        with dashboard_timer(
            operation='get_driver_dashboard_current_job',
            tenant_schema=tenant_schema,
            driver_id=driver_id,
        ):
            with schema_context(tenant_schema):
                ownership = preload_driver_ownership_scope(driver)
                build_state = DashboardBuildState(
                    driver=driver,
                    tenant_schema=tenant_schema,
                    request=request,
                    variant='summary',
                )
                latest_shipment = build_state.get_latest_active_shipment(
                    fetcher=fetch_latest_active_shipment,
                )
                snapshot = build_current_job_snapshot(
                    driver=driver,
                    request=request,
                    latest_shipment=latest_shipment,
                    build_state=build_state,
                )
                payload = sanitize_dashboard_payload(
                    driver=driver,
                    payload={'current_job': snapshot},
                    ownership_scope=ownership,
                )
                data = _serialize_current_job(
                    payload['current_job'],
                    request=request,
                )
                cache_set(
                    tenant_schema=tenant_schema,
                    driver_id=driver_id,
                    slice_name='current_job',
                    data=data,
                )
    except Exception as exc:
        logger.exception(
            'get_driver_dashboard_current_job failed schema=%s: %s',
            tenant_schema,
            exc,
        )
        return {'success': False, 'error': _('mobile.validation.failed')}

    return {'success': True, 'current_job': data}


def get_driver_dashboard_quick_actions(
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    jwt_payload: dict | None = None,
) -> dict[str, Any]:
    """``GET /api/v1/mobile/driver/dashboard/quick-actions/`` — action metadata only."""
    secured = resolve_secure_dashboard_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        request=request,
        jwt_payload=jwt_payload,
    )
    if not secured['success']:
        return {'success': False, 'error': secured['error']}

    sec_ctx = secured['ctx']
    driver = sec_ctx.driver
    tenant_schema = sec_ctx.tenant_schema
    driver_id = str(driver.driver_id)

    cached = cache_get(
        tenant_schema=tenant_schema,
        driver_id=driver_id,
        slice_name='quick_actions',
    )
    if cached is not None:
        return {'success': True, 'quick_actions': cached}

    try:
        with dashboard_timer(
            operation='get_driver_dashboard_quick_actions',
            tenant_schema=tenant_schema,
            driver_id=driver_id,
        ):
            with schema_context(tenant_schema):
                ownership = preload_driver_ownership_scope(driver)
                build_state = DashboardBuildState(
                    driver=driver,
                    tenant_schema=tenant_schema,
                    request=request,
                    variant='summary',
                )
                counters = build_dashboard_counters(driver=driver)
                latest_shipment = build_state.get_latest_active_shipment(
                    fetcher=fetch_latest_active_shipment,
                )
                current_job = build_current_job_snapshot(
                    driver=driver,
                    request=request,
                    latest_shipment=latest_shipment,
                    build_state=build_state,
                )
                actions = build_dashboard_quick_actions(
                    counters=counters,
                    current_job=current_job,
                    request=request,
                    driver=driver,
                    ownership_scope=ownership,
                )
                meta = build_quick_actions_meta(actions=actions)
                actions = sanitize_dashboard_payload(
                    driver=driver,
                    payload={'quick_actions': actions},
                    ownership_scope=ownership,
                )['quick_actions']
                data = _serialize_quick_actions(actions, meta, request=request)
                cache_set(
                    tenant_schema=tenant_schema,
                    driver_id=driver_id,
                    slice_name='quick_actions',
                    data=data,
                )
    except Exception as exc:
        logger.exception(
            'get_driver_dashboard_quick_actions failed schema=%s: %s',
            tenant_schema,
            exc,
        )
        return {'success': False, 'error': _('mobile.validation.failed')}

    return {'success': True, 'quick_actions': data}
