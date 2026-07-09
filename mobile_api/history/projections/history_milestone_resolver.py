"""
History Detail workflow milestones — tenant Action Master aware.

Matches forward action logs by canonical code hints first, then lifecycle
semantics (labels, impacts, flags) so renamed OA-* codes still complete steps.
"""
from __future__ import annotations

from typing import Any, Callable

from iroad_tenants.operation_field_catalog import operation_pod_status_is_complete
from iroad_tenants.operation_execution import action_matches
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    is_delivery_arrival_action,
    is_loading_action,
    is_pickup_action,
    is_unloading_action,
)
from mobile_api.helpers.job_action_resolver import (
    action_is_collect_payment,
    action_is_job_close,
    resolve_collect_payment_action_code,
    resolve_job_close_action_code,
    resolve_unloading_action_code,
)
from tenant_workspace.models import TenantShipment

_MILESTONE_MATCHERS: dict[str, Callable[[Any], bool]] = {
    'pickup': is_pickup_action,
    'loading': lambda action: is_loading_action(action)
    or action_matches(action, 'confirm loaded', 'a4', 'action 4'),
    'in_transit': lambda action: action_matches(
        action,
        'in transit',
        'depart',
        'a5',
        'action 5',
        'shipment in transit',
    ),
    'delivery': is_delivery_arrival_action,
    'pod': lambda action: bool(getattr(action, 'auto_pod_post', False))
    or (
        bool(getattr(action, 'hard_copy_collection', False))
        and action_matches(action, 'pod', 'delivery note', 'custody')
    )
    or action_matches(action, 'upload pod', 'pod', 'a7', 'action 7'),
    'unloading': is_unloading_action,
    'payment': action_is_collect_payment,
    'job_closed': action_is_job_close,
}

_DEFAULT_LABELS: dict[str, str] = {
    'pickup': 'Pickup',
    'loading': 'Loading',
    'in_transit': 'In Transit',
    'delivery': 'Delivery',
    'pod': 'POD',
    'unloading': 'Unloading Completed',
    'payment': 'Collect Payment',
    'job_closed': 'Shipment Completed',
}


def _tenant_schema_from_request(request: Any | None) -> str:
    if request is None:
        return ''
    try:
        from mobile_api.job_detail.services.job_detail_driver_resolver import (
            tenant_schema_for_request,
        )

        return tenant_schema_for_request(request) or ''
    except Exception:
        return ''


def _code_hints_for_step(step_key: str, tenant_schema: str) -> tuple[str, ...]:
    if step_key == 'pickup':
        return ('A2', 'OA-0002')
    if step_key == 'loading':
        return ('A3', 'A4', 'OA-0003', 'OA-0004')
    if step_key == 'in_transit':
        return ('A5', 'OA-0005')
    if step_key == 'delivery':
        return ('A6', 'OA-0006')
    if step_key == 'pod':
        return ('A7', 'OA-0007', 'OA-0008')
    if step_key == 'unloading':
        code = resolve_unloading_action_code(tenant_schema)
        return tuple({code, 'A8', 'OA-0008'} - {''})
    if step_key == 'payment':
        code = resolve_collect_payment_action_code(tenant_schema)
        return tuple({code, 'A9', 'OA-0009'} - {''})
    if step_key == 'job_closed':
        code = resolve_job_close_action_code(tenant_schema)
        return tuple({code, 'A10', 'OA-0010'} - {''})
    return ()


_EARLIEST_LOG_STEPS = frozenset(
    {'pickup', 'loading', 'in_transit', 'delivery', 'pod', 'unloading', 'payment'},
)


def resolve_history_milestone_specs(
    *,
    order_type: str = '',
    tenant_schema: str = '',
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Ordered milestone rows for History Detail workflow_status."""
    schema = (tenant_schema or '').strip()
    is_cod = (order_type or '').strip().upper() == 'COD'
    keys = (
        'pickup',
        'loading',
        'in_transit',
        'delivery',
        'pod',
        'unloading',
        *(['payment'] if is_cod else ()),
        'job_closed',
    )
    specs: list[tuple[str, str, tuple[str, ...]]] = []
    for step_key in keys:
        specs.append(
            (
                step_key,
                _DEFAULT_LABELS[step_key],
                _code_hints_for_step(step_key, schema),
            ),
        )
    return tuple(specs)


def pick_log_for_history_milestone(
    logs: list[Any],
    *,
    step_key: str,
    action_codes: tuple[str, ...],
) -> Any | None:
    """Matching log for a milestone — earliest for forward steps, latest for close."""
    codes = {c.strip().casefold() for c in action_codes if c}
    matched: list[Any] = []
    matcher = _MILESTONE_MATCHERS.get(step_key)
    for log in logs or []:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        code = str(getattr(action, 'action_code', '') or '').strip().casefold()
        if code and code in codes:
            matched.append(log)
            continue
        if matcher is not None and matcher(action):
            matched.append(log)
    if not matched:
        return None
    reverse = step_key not in _EARLIEST_LOG_STEPS
    matched.sort(
        key=lambda row: (
            getattr(row, 'log_date', None) or getattr(row, 'created_at', None),
        ),
        reverse=reverse,
    )
    return matched[0]


def milestone_completed_for_history(
    shipment: Any,
    step_key: str,
    log_row: Any | None,
    *,
    order_type: str = '',
) -> bool:
    """Whether a History Detail milestone row should render for this shipment."""
    if log_row is not None:
        return True
    if infer_milestone_completion_from_shipment(
        shipment,
        step_key,
        order_type=order_type,
    ):
        return True
    if shipment is None:
        return False
    status = str(getattr(shipment, 'shipment_status', '') or '').strip()
    if status == TenantShipment.ShipmentStatus.CLOSED:
        return True
    return False


def infer_milestone_completion_from_shipment(
    shipment: Any,
    step_key: str,
    *,
    order_type: str = '',
) -> bool:
    """Fallback when action log row is missing but terminal column proves the step."""
    if shipment is None:
        return False
    status = str(getattr(shipment, 'shipment_status', '') or '').strip()
    if step_key == 'job_closed':
        return status == TenantShipment.ShipmentStatus.CLOSED
    if step_key == 'payment':
        resolved = (order_type or getattr(shipment, 'order_type', '') or '').strip().upper()
        if resolved != 'COD':
            return False
        return (
            getattr(shipment, 'collection_status', None)
            == TenantShipment.CollectionStatus.COLLECTED
        )
    if step_key == 'pod':
        return operation_pod_status_is_complete(getattr(shipment, 'pod_status', None))
    if step_key == 'unloading':
        if status in {
            TenantShipment.ShipmentStatus.DELIVERED,
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
            TenantShipment.ShipmentStatus.CLOSED,
        }:
            return operation_pod_status_is_complete(getattr(shipment, 'pod_status', None))
    if step_key in {'pickup', 'loading', 'in_transit', 'delivery'}:
        return status in {
            TenantShipment.ShipmentStatus.IN_TRANSIT,
            TenantShipment.ShipmentStatus.AT_DELIVERY,
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
            TenantShipment.ShipmentStatus.DELIVERED,
            TenantShipment.ShipmentStatus.CLOSED,
        }
    return False
