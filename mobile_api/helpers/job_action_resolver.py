"""
Resolve tenant Action Master codes for mobile workflow hints.

Mobile must not hardcode catalog codes (A8, A9, A10, OA-0007, …). Resolution
uses workflow rows first, then tenant Action Master semantics (labels, impacts,
flags), with canonical fallbacks only when schema context is unavailable.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django_tenants.utils import schema_context

from iroad_tenants.operation_execution import action_matches
from iroad_tenants.operation_runtime.impacts import resolve_shipment_status_impact
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    is_delivery_arrival_action,
    is_unloading_action,
    is_unloading_completed_action,
    shipment_delivery_arrival_done,
    shipment_unloading_completed_done,
    shipment_unloading_done,
)
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    action_code_from_action,
    find_allowed_action_row_by_impact,
)
from tenant_workspace.models import TenantOperationAction, TenantShipment

# Last-resort literals for unit tests / missing tenant schema only.
CANONICAL_FALLBACK_COLLECT_PAYMENT_ACTION_CODE = 'A9'
CANONICAL_FALLBACK_JOB_CLOSE_ACTION_CODE = 'A10'
CANONICAL_FALLBACK_UNLOADING_ACTION_CODE = 'A8'
CANONICAL_FALLBACK_DELIVERY_ARRIVAL_ACTION_CODE = 'A6'


def _iter_active_actions(tenant_schema: str):
    schema = (tenant_schema or '').strip()
    if not schema:
        return
    with schema_context(schema):
        yield from (
            TenantOperationAction.objects.exclude(
                status=TenantOperationAction.Status.INACTIVE,
            ).order_by('sequence_number', 'action_code')
        )


def _row_as_action(row: dict[str, Any]) -> SimpleNamespace:
    req = dict(row.get('execution_requirements') or {})
    return SimpleNamespace(
        action_code=row.get('action_code'),
        english_label=(
            row.get('english_label')
            or row.get('action_label')
            or row.get('label')
            or row.get('execution_label')
        ),
        arabic_label=row.get('arabic_label'),
        shipment_status_impact=(
            req.get('shipment_status_impact')
            or row.get('shipment_status_impact')
            or ''
        ),
        auto_shipment_post=req.get('auto_shipment_post'),
        auto_treasury_post=req.get('auto_treasury_post'),
    )


def _lookup_action_by_code(action_code: str, tenant_schema: str) -> Any | None:
    code = (action_code or '').strip()
    if not code or not (tenant_schema or '').strip():
        return None
    with schema_context(tenant_schema.strip()):
        return (
            TenantOperationAction.objects.exclude(
                status=TenantOperationAction.Status.INACTIVE,
            )
            .filter(action_code__iexact=code)
            .first()
        )


def resolve_collect_payment_action(tenant_schema: str) -> Any | None:
    for action in _iter_active_actions(tenant_schema):
        if action_is_collect_payment(action):
            return action
    return None


def resolve_unloading_action(tenant_schema: str) -> Any | None:
    for action in _iter_active_actions(tenant_schema):
        if is_unloading_action(action):
            return action
    return None


def resolve_unloading_completed_action(tenant_schema: str) -> Any | None:
    for action in _iter_active_actions(tenant_schema):
        if is_unloading_completed_action(action):
            return action
    return None


def resolve_delivery_arrival_action(tenant_schema: str) -> Any | None:
    for action in _iter_active_actions(tenant_schema):
        if is_delivery_arrival_action(action):
            return action
    return None


def resolve_job_close_action(tenant_schema: str) -> Any | None:
    schema = (tenant_schema or '').strip()
    if schema:
        from django_tenants.utils import schema_context

        with schema_context(schema):
            from iroad_tenants.operation_runtime.workflow_action_policy import (
                resolve_job_close_operation_action,
            )

            return resolve_job_close_operation_action()
    for action in _iter_active_actions(tenant_schema):
        if action_is_job_close(action):
            return action
    return None


def resolve_collect_payment_action_code(tenant_schema: str) -> str:
    return action_code_from_action(
        resolve_collect_payment_action(tenant_schema),
        fallback=CANONICAL_FALLBACK_COLLECT_PAYMENT_ACTION_CODE,
    )


def resolve_unloading_action_code(tenant_schema: str) -> str:
    return action_code_from_action(
        resolve_unloading_action(tenant_schema),
        fallback=CANONICAL_FALLBACK_UNLOADING_ACTION_CODE,
    )


def resolve_unloading_completed_action_code(tenant_schema: str) -> str:
    return action_code_from_action(
        resolve_unloading_completed_action(tenant_schema),
        fallback='',
    )


def resolve_delivery_arrival_action_code(tenant_schema: str) -> str:
    return action_code_from_action(
        resolve_delivery_arrival_action(tenant_schema),
        fallback=CANONICAL_FALLBACK_DELIVERY_ARRIVAL_ACTION_CODE,
    )


def resolve_job_close_action_code(tenant_schema: str) -> str:
    return action_code_from_action(
        resolve_job_close_action(tenant_schema),
        fallback=CANONICAL_FALLBACK_JOB_CLOSE_ACTION_CODE,
    )


def action_is_job_close(action: Any | None) -> bool:
    """True when Action Master row closes the shipment (impact → Closed)."""
    from iroad_tenants.operation_runtime.workflow_action_policy import (
        action_is_job_close as _policy_action_is_job_close,
    )

    return _policy_action_is_job_close(action)


def action_code_is_job_close(
    action_code: str | None,
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
) -> bool:
    code = (action_code or '').strip()
    if not code:
        return False
    if workflow and row_is_job_close_action(_resolve_action_row(workflow, code)):
        return True
    action = _lookup_action_by_code(code, tenant_schema)
    if action is not None:
        return action_is_job_close(action)
    return False


def action_is_collect_payment(action: Any | None) -> bool:
    """True for COD Payment Collection rows (any tenant label / code)."""
    if action is None:
        return False
    if getattr(action, 'auto_treasury_post', False):
        return True
    if action_is_job_close(action):
        return False
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    if is_pod_upload_action(action):
        return False
    condition = (getattr(action, 'condition_code', '') or '').strip().casefold()
    if condition and 'cod' in condition and 'order_type' in condition:
        return True
    return action_matches(
        action,
        'collect payment',
        'payment collection',
        'cod payment',
        'action 9',
    )


def action_code_is_collect_payment(
    action_code: str | None,
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
) -> bool:
    code = (action_code or '').strip()
    if not code:
        return False
    if workflow and row_is_collect_payment_action(_resolve_action_row(workflow, code)):
        return True
    action = _lookup_action_by_code(code, tenant_schema)
    if action is not None:
        return action_is_collect_payment(action)
    return False


def row_is_unloading_action(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    return is_unloading_action(_row_as_action(row))


def row_is_unloading_completed_action(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    return is_unloading_completed_action(_row_as_action(row))


def row_is_delivery_arrival_action(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    return is_delivery_arrival_action(_row_as_action(row))


def row_is_start_job_action(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    return action_matches(_row_as_action(row), 'start job', 'action 1')


def row_is_confirm_loaded_action(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    req = dict(row.get('execution_requirements') or {})
    if req.get('auto_shipment_post') is True:
        return True
    return action_matches(_row_as_action(row), 'confirm loaded', 'a4', 'action 4')


def row_action_reason_label(row: dict[str, Any] | None, action_code: str = '') -> str:
    if row:
        for key in ('execution_label', 'english_label', 'label'):
            text = str(row.get(key) or '').strip()
            if text:
                return text
    code = (action_code or '').strip()
    return f'Execute {code}' if code else 'Continue the job'


def row_is_collect_payment_action(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    req = dict(row.get('execution_requirements') or {})
    if req.get('auto_treasury_post') is True:
        return True
    return action_is_collect_payment(_row_as_action(row))


def row_is_job_close_action(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    req = dict(row.get('execution_requirements') or {})
    impact = str(
        req.get('shipment_status_impact')
        or row.get('shipment_status_impact')
        or '',
    ).strip()
    if resolve_shipment_status_impact(impact) == TenantShipment.ShipmentStatus.CLOSED:
        return True
    if action_is_job_close(_row_as_action(row)):
        return True
    label = str(
        row.get('english_label')
        or row.get('execution_label')
        or row.get('action_label')
        or row.get('label')
        or '',
    ).casefold()
    return any(needle in label for needle in (
        'end job',
        'job closed',
        'close job',
        'job close',
    ))


def resolve_unloading_action_code_from_context(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
    next_code: str = '',
) -> str:
    code = (next_code or '').strip()
    if code and row_is_unloading_action(_resolve_action_row(workflow, code)):
        return code
    for row in (workflow or {}).get('allowed_actions') or []:
        if isinstance(row, dict) and row_is_unloading_action(row):
            resolved = (row.get('action_code') or '').strip()
            if resolved:
                return resolved
    return resolve_unloading_action_code(tenant_schema)


def resolve_unloading_completed_action_code_from_context(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
    next_code: str = '',
) -> str:
    code = (next_code or '').strip()
    if code and row_is_unloading_completed_action(_resolve_action_row(workflow, code)):
        return code
    for row in (workflow or {}).get('allowed_actions') or []:
        if isinstance(row, dict) and row_is_unloading_completed_action(row):
            resolved = (row.get('action_code') or '').strip()
            if resolved:
                return resolved
    return resolve_unloading_completed_action_code(tenant_schema)


def resolve_delivery_arrival_action_code_from_context(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
    next_code: str = '',
) -> str:
    code = (next_code or '').strip()
    if code and row_is_delivery_arrival_action(_resolve_action_row(workflow, code)):
        return code
    for row in (workflow or {}).get('allowed_actions') or []:
        if isinstance(row, dict) and row_is_delivery_arrival_action(row):
            resolved = (row.get('action_code') or '').strip()
            if resolved:
                return resolved
    return resolve_delivery_arrival_action_code(tenant_schema)


def resolve_collect_payment_action_code_from_context(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
    next_code: str = '',
) -> str:
    code = (next_code or '').strip()
    if code and row_is_collect_payment_action(_resolve_action_row(workflow, code)):
        return code
    row = find_allowed_action_row_by_impact(
        list((workflow or {}).get('allowed_actions') or []),
        'auto_treasury_post',
    )
    resolved = (row.get('action_code') or '').strip()
    if resolved:
        return resolved
    return resolve_collect_payment_action_code(tenant_schema)


def resolve_job_close_action_code_from_context(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
    next_code: str = '',
) -> str:
    code = (next_code or '').strip()
    if code and row_is_job_close_action(_resolve_action_row(workflow, code)):
        return code
    for row in (workflow or {}).get('allowed_actions') or []:
        if isinstance(row, dict) and row_is_job_close_action(row):
            resolved = (row.get('action_code') or '').strip()
            if resolved:
                return resolved
    return resolve_job_close_action_code(tenant_schema)


def _resolve_action_row(
    workflow: dict[str, Any] | None,
    action_code: str,
) -> dict[str, Any]:
    code = (action_code or '').strip().casefold()
    if not code:
        return {}
    for row in (workflow or {}).get('allowed_actions') or []:
        if not isinstance(row, dict):
            continue
        if str(row.get('action_code') or '').strip().casefold() == code:
            return dict(row)
    next_action = dict((workflow or {}).get('next_action') or {})
    if str(next_action.get('action_code') or '').strip().casefold() == code:
        return next_action
    primary = dict((workflow or {}).get('primary_action') or {})
    if str(primary.get('action_code') or '').strip().casefold() == code:
        return primary
    return {}
