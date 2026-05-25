"""
Lightweight timeline row projections with batched media previews.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from iroad_tenants.operation_runtime.impacts import operation_action_matches
from mobile_api.helpers.i18n import get_localized_value
from mobile_api.helpers.timeline_params import timeline_media_per_log
from mobile_api.serializers.driver_profile import safe_media_url
from tenant_workspace.models import TenantOperationActionMedia


def _action_name(log_row, request=None) -> str:
    action = getattr(log_row, 'operation_action', None)
    if action is None:
        return ''
    if request is not None:
        return (
            get_localized_value(
                request,
                action.english_label or action.action_code or '',
                action.arabic_label or '',
            )
            or action.action_code
            or ''
        )
    return (action.english_label or action.action_code or '').strip()


def _driver_name(log_row) -> str:
    label = (getattr(log_row, 'created_by_label', None) or '').strip()
    if label:
        return label[:200]
    driver = getattr(log_row, 'driver', None)
    if driver is None:
        return ''
    return (
        (getattr(driver, 'english_name', None) or '').strip()
        or (getattr(driver, 'arabic_name', None) or '').strip()
        or (getattr(driver, 'driver_code', None) or '').strip()
    )[:200]


def _status_impacts(action) -> dict[str, str | None]:
    if action is None:
        return {
            'shipment': None,
            'movement': None,
            'booking': None,
        }
    return {
        'shipment': (action.shipment_status_impact or '').strip() or None,
        'movement': (action.movement_status_impact or '').strip() or None,
        'booking': (action.booking_status_impact or '').strip() or None,
    }


def _event_flags(action) -> dict[str, bool]:
    if action is None:
        return {
            'is_pod': False,
            'is_cod': False,
            'is_reversal': False,
            'is_status_impact': False,
        }
    is_pod = operation_action_matches(
        action,
        'upload pod',
        'a7',
        'action 7',
        'pod',
        'hard copy',
    ) or bool(getattr(action, 'auto_pod_post', False))
    is_cod = operation_action_matches(
        action,
        'collect payment',
        'a9',
        'action 9',
        'cod',
    )
    is_reversal = operation_action_matches(
        action,
        'reversal',
        'reject pod',
        'reject',
        'r1',
        'r2',
        'r3',
        'r4',
        'cancel shipment',
        'undo',
    )
    impacts = _status_impacts(action)
    is_status = any(impacts.values()) or bool(getattr(action, 'auto_movement_post', False))
    return {
        'is_pod': is_pod,
        'is_cod': is_cod,
        'is_reversal': is_reversal,
        'is_status_impact': is_status,
    }


def batch_media_previews_by_log(
    log_ids: list,
    *,
    request=None,
    per_log_cap: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch capped media preview rows for many logs in one query."""
    if not log_ids:
        return {}
    cap = per_log_cap if per_log_cap is not None else timeline_media_per_log()
    cap = max(0, min(cap, 10))
    desc_max = int(getattr(settings, 'MOBILE_JOB_TIMELINE_DESCRIPTION_MAX', 120) or 120)

    rows = (
        TenantOperationActionMedia.objects.filter(action_log_id__in=log_ids)
        .order_by('action_log_id', 'line_no', 'created_at')
        .only(
            'media_id',
            'action_log_id',
            'line_no',
            'media_type',
            'description',
            'captured_at',
            'file',
        )
    )

    out: dict[str, list[dict[str, Any]]] = {}
    for media in rows:
        key = str(media.action_log_id)
        bucket = out.setdefault(key, [])
        if len(bucket) >= cap:
            continue
        description = (media.description or '').strip()
        if len(description) > desc_max:
            description = description[: desc_max - 1] + '…'
        bucket.append(
            {
                'media_id': str(media.media_id),
                'line_no': media.line_no,
                'media_type': (media.media_type or '').strip(),
                'description': description,
                'captured_at': media.captured_at.isoformat() if media.captured_at else None,
                'preview_url': safe_media_url(request, media.file),
                'has_file': bool(getattr(media.file, 'name', None)),
            }
        )
    return out


def project_timeline_item(
    log_row,
    *,
    request=None,
    media_previews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    action = getattr(log_row, 'operation_action', None)
    events = _event_flags(action)
    impacts = _status_impacts(action)
    return {
        'log_id': str(log_row.log_id),
        'log_no': log_row.log_no,
        'action_name': _action_name(log_row, request),
        'action_code': action.action_code if action else None,
        'execution_time': log_row.log_date.isoformat() if log_row.log_date else None,
        'driver_name': _driver_name(log_row),
        'gps': {
            'latitude': (log_row.latitude or '').strip(),
            'longitude': (log_row.longitude or '').strip(),
            'map_link': (log_row.map_link or '').strip(),
        },
        'notes': (log_row.notes or '').strip(),
        'media_previews': media_previews or [],
        'media_count': len(media_previews or []),
        'status_impacts': impacts,
        'events': events,
        'source': (log_row.source or '').strip(),
        'source_channel': (log_row.source_channel or '').strip(),
        'shipment_id': str(log_row.shipment_id) if log_row.shipment_id else None,
        'movement_id': str(log_row.truck_movement_id) if log_row.truck_movement_id else None,
    }
