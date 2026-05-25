"""
Lightweight Job Detail DTO projections (flat-first, no portal serializers).
"""

from __future__ import annotations

from typing import Any, Literal

from mobile_api.helpers.i18n import get_localized_value
from mobile_api.helpers.job_card_projections import (
    flatten_route_fields,
    flatten_truck_fields,
    iso_job_timestamp,
    project_operational_indicators,
    project_pod_cod_fields,
    project_route_from_movement,
    project_route_from_shipment,
)
from mobile_api.helpers.job_list_next_action import (
    build_movement_next_action_hint,
    build_shipment_next_action_hint,
)
from mobile_api.services.driver_dashboard_current_job import project_truck_summary

JobType = Literal['shipment', 'movement']


def project_driver_context(*, driver, tenant_user=None, request=None) -> dict[str, Any]:
    if driver is None:
        return {
            'driver_id': None,
            'driver_code': '',
            'display_name': '',
            'arabic_name': '',
        }
    english = (getattr(driver, 'english_name', None) or '').strip()
    arabic = (getattr(driver, 'arabic_name', None) or '').strip()
    display = english or arabic or (getattr(driver, 'driver_code', None) or '')
    if request is not None:
        display = get_localized_value(request, english or display, arabic or display)
    return {
        'driver_id': str(getattr(driver, 'driver_id', driver.pk)),
        'driver_code': getattr(driver, 'driver_code', None) or '',
        'display_name': display,
        'english_name': english,
        'arabic_name': arabic,
        'tenant_user_id': str(tenant_user.user_id) if tenant_user is not None else None,
    }


def project_allowed_actions_summary(allowed_block: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize engine payload (full metadata rows when present)."""
    if not allowed_block:
        return {
            'context_label': '',
            'count': 0,
            'actions': [],
            'primary_action': None,
            'workflow_source': 'operation_execution.get_allowed_actions',
        }
    actions = list(allowed_block.get('actions') or [])
    primary = allowed_block.get('primary_action') or (actions[0] if actions else None)
    return {
        'context_label': allowed_block.get('context_label') or '',
        'count': allowed_block.get('count', len(actions)),
        'actions': actions,
        'primary_action': primary,
        'workflow_source': allowed_block.get(
            'workflow_source',
            'operation_execution.get_allowed_actions',
        ),
        'current_stage': allowed_block.get('current_stage') or '',
    }


def project_workflow_state(
    *,
    job_type: JobType,
    status_block: dict[str, Any],
    execution_state: dict[str, Any],
    indicators: dict[str, bool],
    allowed_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        'operational_stage': status_block.get('operational_stage'),
        'shipment_status': status_block.get('shipment_status'),
        'movement_status': status_block.get('movement_status'),
        'has_active_movement': bool(status_block.get('has_active_movement')),
        'derived_status': execution_state.get('authoritative_status')
        or execution_state.get('derived_status'),
        'status_in_sync': bool(execution_state.get('in_sync', True))
        and not execution_state.get('has_drift', False),
        'allowed_actions_count': allowed_summary.get('count', 0),
        'needs_pod': indicators.get('needs_pod', False),
        'needs_cod': indicators.get('needs_cod', False),
        'is_active': indicators.get('is_active', False),
        'is_empty_move': indicators.get('is_empty_move', False),
        'job_type': job_type,
    }


def _build_job_summary(
    *,
    job_type: JobType,
    job_id: str,
    job_no: str,
    current_status: str,
    shipment_block: dict[str, Any] | None,
    movement_block: dict[str, Any] | None,
    route_flat: dict[str, str],
    next_action_hint: str | None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        'job_id': job_id,
        'job_type': job_type,
        'job_no': job_no,
        'current_status': current_status or '',
        'next_action_hint': next_action_hint,
        **route_flat,
    }
    if shipment_block:
        summary.update(
            {
                'shipment_id': shipment_block.get('shipment_id'),
                'shipment_no': shipment_block.get('shipment_no'),
                'booking_no': shipment_block.get('booking_no'),
                'order_type': shipment_block.get('order_type'),
                'shipment_date': shipment_block.get('shipment_date'),
            }
        )
    if movement_block:
        summary.update(
            {
                'movement_id': movement_block.get('movement_id'),
                'movement_no': movement_block.get('movement_no'),
                'movement_source': movement_block.get('movement_source'),
                'empty_move_reason': movement_block.get('empty_move_reason'),
                'movement_date': movement_block.get('movement_date'),
            }
        )
    if shipment_block and movement_block:
        summary['linked_movement_id'] = movement_block.get('movement_id')
        summary['linked_movement_no'] = movement_block.get('movement_no')
    if movement_block and shipment_block:
        summary['linked_shipment_id'] = shipment_block.get('shipment_id')
        summary['linked_shipment_no'] = shipment_block.get('shipment_no')
    return summary


def build_job_detail_dto(
    *,
    raw_snapshot: dict[str, Any],
    driver,
    tenant_user=None,
    shipment_row=None,
    movement_row=None,
    request=None,
) -> dict[str, Any]:
    """
    Normalize ``JobDetailSnapshotService`` output into the mobile Job Detail contract.
    """
    job_type: JobType = raw_snapshot.get('job_type') or 'shipment'
    status_block = raw_snapshot.get('status') or {}
    execution_state = raw_snapshot.get('execution_state') or {}
    route_nested = raw_snapshot.get('route') or {}
    route_flat = flatten_route_fields(route_nested)
    truck_nested = project_truck_summary(
        (shipment_row.truck if shipment_row is not None else None)
        or (getattr(movement_row, 'truck', None) if movement_row is not None else None)
    )
    truck_flat = flatten_truck_fields(truck_nested)

    shipment_block = raw_snapshot.get('shipment')
    movement_block = raw_snapshot.get('movement')

    if job_type == 'shipment' and shipment_row is not None:
        indicators = project_operational_indicators(
            job_type='shipment',
            shipment=shipment_row,
        )
        pod_cod = project_pod_cod_fields(shipment=shipment_row)
        next_hint = None
        current_status = shipment_row.shipment_status or ''
    elif job_type == 'movement' and movement_row is not None:
        linked = shipment_row
        indicators = project_operational_indicators(
            job_type='movement',
            movement=movement_row,
        )
        pod_cod = (
            project_pod_cod_fields(shipment=linked)
            if linked is not None
            else {
                'pod_status': '',
                'cod_status': '',
                'collection_status': '',
                'is_cod_order': False,
                'is_pod_pending': False,
                'is_cod_pending': False,
            }
        )
        next_hint = None
        current_status = movement_row.status or ''
        if linked is None:
            route_nested = project_route_from_movement(movement_row, request)
            route_flat = flatten_route_fields(route_nested)
    else:
        indicators = {
            'needs_pod': False,
            'needs_cod': False,
            'is_active': False,
            'is_empty_move': False,
        }
        pod_cod = {}
        next_hint = None
        current_status = status_block.get('operational_stage') or ''

    allowed_summary = project_allowed_actions_summary(raw_snapshot.get('allowed_actions'))
    engine_primary = allowed_summary.get('primary_action')
    if engine_primary and isinstance(engine_primary, dict):
        next_hint = engine_primary.get('execution_label') or engine_primary.get(
            'action_name'
        )
    elif next_hint is None:
        if job_type == 'shipment' and shipment_row is not None:
            next_hint = build_shipment_next_action_hint(shipment_row)
        elif job_type == 'movement' and movement_row is not None:
            next_hint = build_movement_next_action_hint(
                movement_row,
                shipment=shipment_row,
            )
    workflow_state = project_workflow_state(
        job_type=job_type,
        status_block=status_block,
        execution_state=execution_state,
        indicators=indicators,
        allowed_summary=allowed_summary,
    )

    execution_stage = (
        execution_state.get('operational_stage')
        or status_block.get('operational_stage')
        or current_status
    )
    auth_status = execution_state.get('authoritative_status') or execution_state.get(
        'derived_status'
    )
    if auth_status and job_type == 'shipment':
        current_status = auth_status

    job_summary = _build_job_summary(
        job_type=job_type,
        job_id=raw_snapshot.get('job_id') or '',
        job_no=raw_snapshot.get('job_no') or '',
        current_status=current_status,
        shipment_block=shipment_block,
        movement_block=movement_block,
        route_flat=route_flat,
        next_action_hint=next_hint,
    )

    return {
        'job_summary': job_summary,
        'job_type': job_type,
        'job_id': raw_snapshot.get('job_id'),
        'job_no': raw_snapshot.get('job_no'),
        'execution_stage': execution_stage,
        'current_workflow_state': workflow_state,
        'shipment': shipment_block,
        'movement': movement_block,
        'status': status_block,
        'execution_state': execution_state,
        'route': route_nested,
        'route_summary': route_flat.get('route_summary') or '',
        'from_location': route_flat.get('from_location') or '',
        'to_location': route_flat.get('to_location') or '',
        'truck': truck_nested,
        'truck_summary': truck_flat,
        'driver_context': project_driver_context(
            driver=driver,
            tenant_user=tenant_user,
            request=request,
        ),
        'pod': raw_snapshot.get('pod'),
        'cod': raw_snapshot.get('cod'),
        'pod_status': pod_cod.get('pod_status', ''),
        'cod_status': pod_cod.get('cod_status', ''),
        'collection_status': pod_cod.get('collection_status', ''),
        'latest_action': raw_snapshot.get('latest_action'),
        'timeline_preview': raw_snapshot.get('timeline_preview') or [],
        'allowed_actions_summary': allowed_summary,
        'operational_indicators': indicators,
        'next_action_hint': next_hint,
        'updated_at': iso_job_timestamp(
            getattr(shipment_row or movement_row, 'updated_at', None)
        ),
    }
