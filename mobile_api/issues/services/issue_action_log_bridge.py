"""
Append Operation Action Log rows for driver issue / support reports.

PCS §3.1 — workflow execution records standalone support events (Incident Report)
in ``TenantOperationActionLog`` alongside the operational issue staging row.
"""
from __future__ import annotations

from typing import Any, Mapping

from django.utils import timezone

from iroad_tenants.operation_runtime.action_master_catalog import (
    resolve_incident_report_action,
)
from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER


def append_incident_report_action_log(
    *,
    shipment: Any | None = None,
    movement: Any | None = None,
    driver,
    payload: Mapping[str, Any],
    client_issue_id: str,
    tenant_schema: str = '',
    created_by_label: str = '',
) -> Any | None:
    """
    Mirror a new issue report into Action Log using the tenant Incident Report action.

    Idempotent on ``client_issue_id`` — safe on issue-report replays.
    """
    from tenant_workspace.models import TenantOperationActionLog

    operation_action = resolve_incident_report_action()
    if operation_action is None or (shipment is None and movement is None):
        return None

    from mobile_api.execution.evidence.action_log_media_persistence import (
        normalize_media_items,
        persist_action_log_media_rows,
    )
    from tenant_workspace.ops_display import driver_label

    schema = (tenant_schema or '').strip()
    driver_id = str(getattr(driver, 'pk', '') or getattr(driver, 'driver_id', '') or '').strip()
    idempotency_key = f'incident-report:{schema}:{driver_id}:{client_issue_id}'
    source_ref = f'issue-report:{client_issue_id}'

    existing_qs = TenantOperationActionLog.objects.filter(
        idempotency_key=idempotency_key,
    )
    existing = existing_qs.first()
    if existing is None:
        lookup = TenantOperationActionLog.objects.filter(
            source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
            source_ref=source_ref,
        )
        if movement is not None:
            existing = lookup.filter(truck_movement_id=movement.pk).first()
        elif shipment is not None:
            existing = lookup.filter(shipment_id=shipment.pk).first()
    if existing is not None:
        return existing

    from iroad_tenants.views import (
        OPERATION_ACTION_LOG_AUTO_FORM_CODE,
        OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
        OPERATION_ACTION_LOG_REF_PREFIX,
        _next_auto_number_for_form,
    )

    issue_type = (payload.get('issue_type') or '').strip()
    severity = (payload.get('severity') or '').strip()
    notes = str(payload.get('notes') or '').strip()
    note_parts = [
        part
        for part in (
            notes,
            f'issue_type={issue_type}' if issue_type else '',
            f'severity={severity}' if severity else '',
        )
        if part
    ]
    log_notes = ' · '.join(note_parts)

    log_no = ''
    log_sequence = 0
    for _ in range(10):
        log_no, log_sequence = _next_auto_number_for_form(
            form_code=OPERATION_ACTION_LOG_AUTO_FORM_CODE,
            form_label=OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
            prefix=OPERATION_ACTION_LOG_REF_PREFIX,
        )
        if not TenantOperationActionLog.objects.filter(log_no=log_no).exists():
            break
    if TenantOperationActionLog.objects.filter(log_no=log_no).exists():
        return None

    latitude = str(payload.get('latitude') or '').strip()[:32]
    longitude = str(payload.get('longitude') or '').strip()[:32]
    map_link = ''
    if latitude and longitude:
        from iroad_tenants.fleet_gps_tracking import build_google_maps_link

        map_link = build_google_maps_link(latitude, longitude, '')

    truck = None
    if shipment is not None:
        truck = getattr(shipment, 'truck', None)
    elif movement is not None:
        truck = getattr(movement, 'truck', None)

    action_log = TenantOperationActionLog.objects.create(
        log_no=log_no,
        log_sequence=log_sequence,
        log_date=timezone.now(),
        operation_action=operation_action,
        source='Mobile',
        source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
        source_ref=source_ref,
        idempotency_key=idempotency_key,
        notes=log_notes,
        booking=getattr(shipment, 'booking', None) if shipment is not None else None,
        shipment=shipment,
        truck_movement=movement,
        truck=truck,
        driver=driver,
        latitude=latitude,
        longitude=longitude,
        map_link=map_link[:500],
        created_by_label=(created_by_label or driver_label(driver))[:200],
    )

    media_items = normalize_media_items(list(payload.get('media') or []))
    if media_items:
        persist_action_log_media_rows(
            action_log,
            media_items,
            replace_existing=True,
        )
    return action_log
