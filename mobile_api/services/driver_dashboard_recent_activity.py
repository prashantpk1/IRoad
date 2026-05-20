"""
mobile_api/services/driver_dashboard_recent_activity.py

Lightweight merged activity feed for the driver home dashboard.

Merges capped slices from action logs, shipments, movements, and POD documents.
No full history, no deep nested serializers, no per-row action scans.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils.translation import gettext as _

from mobile_api.helpers.dashboard_activity import (
    ACTIVITY_TYPE_ACTION,
    ACTIVITY_TYPE_MOVEMENT,
    ACTIVITY_TYPE_POD,
    ACTIVITY_TYPE_SHIPMENT,
    clamp_activity_limit,
    iso_timestamp,
    per_source_fetch_cap,
    resolve_activity_limit_from_settings,
    to_sort_datetime,
)
from mobile_api.helpers.dashboard_route import build_shipment_route_summary
from mobile_api.helpers.i18n import get_localized_value

_ACTION_LOG_ONLY = (
    'log_id',
    'log_no',
    'log_date',
    'source',
    'source_channel',
    'shipment_id',
    'truck_movement_id',
    'operation_action_id',
)

_SHIPMENT_ACTIVITY_ONLY = (
    'shipment_id',
    'shipment_no',
    'shipment_status',
    'pod_status',
    'updated_at',
    'route_display',
)

_MOVEMENT_ACTIVITY_ONLY = (
    'movement_id',
    'movement_no',
    'status',
    'updated_at',
    'shipment_id',
)

_POD_DOC_ONLY = (
    'document_id',
    'record_no',
    'document_type',
    'status',
    'updated_at',
    'shipment_id',
)


def _action_projection(log_row, request=None) -> dict[str, Any]:
    action = getattr(log_row, 'operation_action', None)
    code = None
    label = ''
    if action is not None:
        code = action.action_code
        label = get_localized_value(
            request,
            getattr(action, 'english_label', '') or code or '',
            getattr(action, 'arabic_label', '') or '',
        )
    shipment = getattr(log_row, 'shipment', None)
    movement = getattr(log_row, 'truck_movement', None)
    occurred_at = iso_timestamp(log_row.log_date)
    title = label or code or str(_('mobile.dashboard.activity.action'))
    route_summary = ''
    if shipment is not None:
        route_summary = build_shipment_route_summary(shipment, request).get('summary', '')

    return {
        'activity_type': ACTIVITY_TYPE_ACTION,
        'occurred_at': occurred_at,
        'title': title,
        'route_summary': route_summary,
        'action_code': code,
        'action_label': label or None,
        'shipment_id': str(shipment.shipment_id) if shipment else None,
        'shipment_no': shipment.shipment_no if shipment else None,
        'movement_id': str(movement.movement_id) if movement else None,
        'movement_no': movement.movement_no if movement else None,
        'pod_status': None,
        'source': log_row.source or '',
        'log_id': str(log_row.log_id),
        'log_no': log_row.log_no,
        'log_date': occurred_at,
        '_sort_at': to_sort_datetime(log_row.log_date),
    }


def _shipment_projection(shipment, request=None) -> dict[str, Any]:
    route = build_shipment_route_summary(shipment, request)
    occurred_at = iso_timestamp(shipment.updated_at)
    title = str(
        _('mobile.dashboard.activity.shipment %(shipment_no)s — %(status)s')
        % {
            'shipment_no': shipment.shipment_no,
            'status': shipment.shipment_status,
        }
    )
    return {
        'activity_type': ACTIVITY_TYPE_SHIPMENT,
        'occurred_at': occurred_at,
        'title': title,
        'route_summary': route.get('summary', ''),
        'action_code': None,
        'action_label': None,
        'shipment_id': str(shipment.shipment_id),
        'shipment_no': shipment.shipment_no,
        'movement_id': None,
        'movement_no': None,
        'pod_status': shipment.pod_status or None,
        'source': 'shipment',
        'log_id': None,
        'log_no': None,
        'log_date': occurred_at,
        '_sort_at': to_sort_datetime(shipment.updated_at),
    }


def _movement_projection(movement, request=None) -> dict[str, Any]:
    shipment = getattr(movement, 'shipment', None)
    route_summary = ''
    if shipment is not None:
        route_summary = build_shipment_route_summary(shipment, request).get('summary', '')

    occurred_at = iso_timestamp(movement.updated_at)
    title = str(
        _('mobile.dashboard.activity.movement %(movement_no)s — %(status)s')
        % {
            'movement_no': movement.movement_no,
            'status': movement.status,
        }
    )
    return {
        'activity_type': ACTIVITY_TYPE_MOVEMENT,
        'occurred_at': occurred_at,
        'title': title,
        'route_summary': route_summary,
        'action_code': None,
        'action_label': None,
        'shipment_id': str(shipment.shipment_id) if shipment else None,
        'shipment_no': shipment.shipment_no if shipment else None,
        'movement_id': str(movement.movement_id),
        'movement_no': movement.movement_no,
        'pod_status': None,
        'source': 'movement',
        'log_id': None,
        'log_no': None,
        'log_date': occurred_at,
        '_sort_at': to_sort_datetime(movement.updated_at),
    }


def _pod_projection(document, request=None) -> dict[str, Any]:
    shipment = getattr(document, 'shipment', None)
    route_summary = ''
    pod_status = None
    if shipment is not None:
        route_summary = build_shipment_route_summary(shipment, request).get('summary', '')
        pod_status = shipment.pod_status or None

    occurred_at = iso_timestamp(document.updated_at)
    title = str(
        _('mobile.dashboard.activity.pod %(record_no)s — %(status)s')
        % {
            'record_no': document.record_no,
            'status': document.status,
        }
    )
    return {
        'activity_type': ACTIVITY_TYPE_POD,
        'occurred_at': occurred_at,
        'title': title,
        'document_id': str(document.document_id),
        'route_summary': route_summary,
        'action_code': None,
        'action_label': None,
        'shipment_id': str(shipment.shipment_id) if shipment else None,
        'shipment_no': shipment.shipment_no if shipment else None,
        'movement_id': None,
        'movement_no': None,
        'pod_status': pod_status,
        'source': 'pod_document',
        'log_id': None,
        'log_no': None,
        'log_date': occurred_at,
        '_sort_at': to_sort_datetime(document.updated_at),
    }


def _strip_internal_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith('_')}


def fetch_action_activity_candidates(*, driver, cap: int, request=None) -> list[dict[str, Any]]:
    from mobile_api.helpers.dashboard_security import action_log_queryset_for_driver

    rows = (
        action_log_queryset_for_driver(driver)
        .only(*_ACTION_LOG_ONLY)
        .select_related(
            'operation_action',
            'shipment',
            'shipment__loading_address',
            'shipment__delivery_address',
            'truck_movement',
        )
        .order_by('-log_date', '-created_at')[:cap]
    )
    return [_action_projection(row, request) for row in rows]


def fetch_shipment_activity_candidates(*, driver, cap: int, request=None) -> list[dict[str, Any]]:
    from mobile_api.helpers.dashboard_security import shipment_queryset_for_driver

    rows = (
        shipment_queryset_for_driver(driver)
        .only(*_SHIPMENT_ACTIVITY_ONLY)
        .select_related('loading_address', 'delivery_address')
        .order_by('-updated_at', '-created_at')[:cap]
    )
    return [_shipment_projection(row, request) for row in rows]


def fetch_movement_activity_candidates(*, driver, cap: int, request=None) -> list[dict[str, Any]]:
    from mobile_api.helpers.dashboard_security import movement_queryset_for_driver

    rows = (
        movement_queryset_for_driver(driver)
        .only(*_MOVEMENT_ACTIVITY_ONLY)
        .select_related(
            'shipment',
            'shipment__loading_address',
            'shipment__delivery_address',
        )
        .order_by('-updated_at', '-created_at')[:cap]
    )
    return [_movement_projection(row, request) for row in rows]


def fetch_pod_activity_candidates(
    *,
    driver,
    cap: int,
    request=None,
    shipment_scope_pks: list | None = None,
) -> list[dict[str, Any]]:
    from tenant_workspace.models import TenantShipmentDocument

    scope_pks = shipment_scope_pks
    if scope_pks is None:
        from mobile_api.helpers.dashboard_aggregations import driver_shipment_scope_pk_list

        scope_pks = driver_shipment_scope_pk_list(driver)
    if not scope_pks:
        return []

    rows = (
        TenantShipmentDocument.objects.filter(shipment_id__in=scope_pks)
        .filter(
            Q(is_delivery_note=True) | Q(document_type__iexact='POD'),
        )
        .only(*_POD_DOC_ONLY)
        .select_related(
            'shipment',
            'shipment__loading_address',
            'shipment__delivery_address',
        )
        .order_by('-updated_at', '-created_at')[:cap]
    )
    return [_pod_projection(row, request) for row in rows]


def merge_activity_feed(candidates: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """Sort merged candidates by time descending and return top ``limit`` rows."""
    ordered = sorted(
        candidates,
        key=lambda row: row.get('_sort_at') or to_sort_datetime(None),
        reverse=True,
    )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for row in ordered:
        entity_id = (
            row.get('log_id')
            or row.get('document_id')
            or row.get('movement_id')
            or row.get('shipment_id')
            or ''
        )
        key = (row.get('activity_type') or '', str(entity_id), row.get('occurred_at'))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(_strip_internal_fields(row))
        if len(deduped) >= limit:
            break
    return deduped


def _summary_skip_pod_activity(variant: str) -> bool:
    if variant != 'summary':
        return False
    return bool(
        getattr(settings, 'MOBILE_API_DASHBOARD_SUMMARY_SKIP_POD_ACTIVITY', True)
    )


def build_recent_activity_feed(
    *,
    driver,
    request=None,
    limit: int | None = None,
    variant: str = 'full',
    build_state=None,
    inject_shipment_row=None,
) -> dict[str, Any]:
    """
    Build capped merged feed: ``{ limit, items }``.
    """
    resolved_limit = clamp_activity_limit(
        limit,
        default=resolve_activity_limit_from_settings(variant=variant),
    )
    source_cap = per_source_fetch_cap(resolved_limit)

    shipment_scope_pks = None
    if build_state is not None:
        shipment_scope_pks = build_state.shipment_scope_pks()

    candidates: list[dict[str, Any]] = []
    candidates.extend(
        fetch_action_activity_candidates(driver=driver, cap=source_cap, request=request)
    )

    shipment_rows = fetch_shipment_activity_candidates(
        driver=driver,
        cap=source_cap,
        request=request,
    )
    if inject_shipment_row is not None:
        injected = _shipment_projection(inject_shipment_row, request)
        inject_id = injected.get('shipment_id')
        shipment_rows = [
            row
            for row in shipment_rows
            if row.get('shipment_id') != inject_id
        ]
        shipment_rows.insert(0, injected)
        shipment_rows = shipment_rows[:source_cap]
    candidates.extend(shipment_rows)

    candidates.extend(
        fetch_movement_activity_candidates(driver=driver, cap=source_cap, request=request)
    )
    if not _summary_skip_pod_activity(variant):
        candidates.extend(
            fetch_pod_activity_candidates(
                driver=driver,
                cap=source_cap,
                request=request,
                shipment_scope_pks=shipment_scope_pks,
            )
        )

    items = merge_activity_feed(candidates, limit=resolved_limit)
    return {
        'limit': resolved_limit,
        'items': items,
    }


def build_recent_activity(
    *,
    driver,
    request=None,
    limit: int | None = None,
    variant: str = 'full',
    build_state=None,
    inject_shipment_row=None,
) -> list[dict[str, Any]]:
    """Dashboard ``recent_activity`` list (items only, backward compatible)."""
    return build_recent_activity_feed(
        driver=driver,
        request=request,
        limit=limit,
        variant=variant,
        build_state=build_state,
        inject_shipment_row=inject_shipment_row,
    )['items']


def _parse_limit_query(request) -> int | None:
    if request is None:
        return None
    raw = getattr(request, 'query_params', None) or getattr(request, 'GET', None)
    if not raw:
        return None
    value = raw.get('limit')
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_driver_recent_activity(
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    jwt_payload: dict | None = None,
) -> dict[str, Any]:
    """
    ``GET /api/v1/mobile/driver/dashboard/recent-activity/?limit=5..10``
    """
    import logging

    from django.utils.translation import gettext as _
    from django_tenants.utils import schema_context

    from mobile_api.serializers.driver_dashboard_activity import (
        DashboardRecentActivityFeedSerializer,
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
    limit = _parse_limit_query(request)

    try:
        with schema_context(tenant_schema):
            feed = build_recent_activity_feed(
                driver=driver,
                request=request,
                limit=limit,
                variant='full',
            )
            data = DashboardRecentActivityFeedSerializer(instance=feed).data
    except Exception as exc:
        logger.exception(
            'get_driver_recent_activity failed schema=%s user_id=%s: %s',
            tenant_schema,
            user_id,
            exc,
        )
        return {'success': False, 'error': _('mobile.validation.failed')}

    return {'success': True, 'activity': data}
