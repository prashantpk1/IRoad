"""
mobile_api/pod_capture/services/pod_capture_action_resolver.py

Resolve POD Action Master rows and tenant action codes from operation-impact
flags — not hardcoded A7 / A7H strings.
"""
from __future__ import annotations

from typing import Any

from django_tenants.utils import schema_context

from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    is_hard_pod_action,
    is_pod_upload_action,
)

CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE = 'A7'
CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE = 'A7H'

# Backward-compatible aliases used by older imports/tests.
POD_DIGITAL_ACTION_CODE = CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE
HARD_POD_ACTION_CODE = CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE


def _timeline_row_performed(row: dict[str, Any]) -> bool:
    return bool(row.get('is_performed')) or str(row.get('timeline_state') or '') == 'performed'


def _timeline_unloading_completed_performed(preview: list[Any] | None) -> bool:
    from mobile_api.helpers.job_action_resolver import row_is_unloading_completed_action

    for row in preview or []:
        if not isinstance(row, dict):
            continue
        if row_is_unloading_completed_action(row) and _timeline_row_performed(row):
            return True
    return False


def _timeline_prior_steps_performed(
    preview: list[Any] | None,
    *,
    target_row: dict[str, Any],
) -> bool:
    target_seq = int(target_row.get('sequence_number') or 0)
    if target_seq <= 1:
        return True
    for row in preview or []:
        if not isinstance(row, dict):
            continue
        seq = int(row.get('sequence_number') or 0)
        if seq <= 0 or seq >= target_seq:
            continue
        if not _timeline_row_performed(row):
            return False
    return True


def timeline_pod_step_is_actionable(
    row: dict[str, Any] | None,
    *,
    shipment: Any | None = None,
    timeline_preview: list[Any] | None = None,
) -> bool:
    """POD timeline row may open capture — never before unloading completed."""
    if not row:
        return False
    if _timeline_row_performed(row):
        return False
    preview = list(timeline_preview or [])
    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        shipment_ready_for_pod_capture,
    )

    if shipment is not None and shipment_ready_for_pod_capture(shipment):
        return True
    if not preview:
        return False
    if not _timeline_unloading_completed_performed(preview):
        return False
    return _timeline_prior_steps_performed(preview, target_row=row)


def action_code_from_action(action: Any | None, *, fallback: str) -> str:
    code = (getattr(action, 'action_code', None) or '').strip()
    return code or fallback


def digital_action_code_from_action(
    action: Any | None,
    *,
    tenant_schema: str = '',
    fallback: str = CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE,
) -> str:
    """Tenant action code for digital POD execute — never hardcode A7 when action is known."""
    code = action_code_from_action(action, fallback='')
    if code:
        return code
    if (tenant_schema or '').strip():
        return resolve_digital_pod_action_code(tenant_schema)
    return fallback


def _iter_active_actions(tenant_schema: str):
    schema = (tenant_schema or '').strip()
    if not schema:
        return
    with schema_context(schema):
        from tenant_workspace.models import TenantOperationAction

        yield from (
            TenantOperationAction.objects.exclude(
                status=TenantOperationAction.Status.INACTIVE,
            )
            .order_by('sequence_number', 'action_code')
        )


def resolve_digital_pod_action(tenant_schema: str) -> Any | None:
    """
    Active tenant action for digital POD upload (``auto_pod_post``).

    Includes combined Upload POD rows (``auto_pod_post`` + ``hard_copy_collection``),
    e.g. OA-0008 — hard copy is step 2, not a separate digital action.
    """
    label_fallback = None
    for action in _iter_active_actions(tenant_schema):
        if getattr(action, 'auto_pod_post', False):
            return action
        if label_fallback is None and is_pod_upload_action(action) and not is_hard_pod_action(action):
            label_fallback = action
    return label_fallback


def resolve_hard_copy_pod_action(tenant_schema: str) -> Any | None:
    """Active tenant action for hard-copy custody confirmation."""
    for action in _iter_active_actions(tenant_schema):
        if getattr(action, 'hard_copy_collection', False):
            return action
        if is_hard_pod_action(action):
            return action
    return None


def resolve_default_pod_action(tenant_schema: str) -> Any | None:
    """
    Default POD capture action — digital upload preferred over hard-copy step.
    """
    digital = resolve_digital_pod_action(tenant_schema)
    if digital is not None:
        return digital
    return resolve_hard_copy_pod_action(tenant_schema)


def resolve_digital_pod_action_code(tenant_schema: str) -> str:
    return action_code_from_action(
        resolve_digital_pod_action(tenant_schema),
        fallback=CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE,
    )


def resolve_hard_copy_pod_action_code(tenant_schema: str) -> str:
    hard = resolve_hard_copy_pod_action(tenant_schema)
    code = action_code_from_action(hard, fallback='')
    if code:
        return code
    schema = (tenant_schema or '').strip()
    if schema:
        digital_fallback = resolve_digital_pod_action_code(schema)
        if digital_fallback:
            return digital_fallback
    return CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE


def row_has_hard_copy_collection(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    req = dict(row.get('execution_requirements') or {})
    if req.get('hard_copy_collection') is True:
        return True
    code = str(row.get('action_code') or '').strip().upper()
    return code == CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE


def _row_as_operation_action(row: dict[str, Any]) -> Any:
    from types import SimpleNamespace

    req = dict(row.get('execution_requirements') or {})
    return SimpleNamespace(
        action_code=row.get('action_code') or '',
        english_label=(
            row.get('english_label')
            or row.get('action_label')
            or row.get('action_name')
            or row.get('execution_label')
            or row.get('label')
            or ''
        ),
        auto_pod_post=req.get('auto_pod_post') is True,
        hard_copy_collection=req.get('hard_copy_collection') is True,
        shipment_status_impact=row.get('shipment_status_impact') or '',
    )


def row_has_digital_pod_upload(row: dict[str, Any] | None) -> bool:
    """True for digital POD upload — flag, label, or canonical code."""
    if not row:
        return False
    if str(row.get('action') or '').strip() == 'go_to_pod_capture':
        return True
    from mobile_api.pod_capture.services.pod_capture_screen_routing import (
        POD_CAPTURE_SCREEN,
    )

    if str(row.get('screen') or '').strip() == POD_CAPTURE_SCREEN:
        return True
    if str(row.get('event_type') or '').strip().casefold() == 'pod':
        return True
    req = dict(row.get('execution_requirements') or {})
    if req.get('auto_pod_post') is True:
        return True
    if is_pod_upload_action(_row_as_operation_action(row)):
        return True
    code = str(row.get('action_code') or '').strip().upper()
    return code == CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE


def find_pod_upload_row_in_allowed(
    allowed_actions: list[Any] | None,
) -> dict[str, Any]:
    for row in allowed_actions or []:
        if isinstance(row, dict) and row_has_digital_pod_upload(row):
            return dict(row)
    return {}


def find_pod_upload_row_in_timeline(
    timeline: dict[str, Any] | list[Any] | None,
) -> dict[str, Any]:
    """First pending POD step from Job Detail timeline preview."""
    preview: list[Any]
    if isinstance(timeline, dict):
        preview = list(timeline.get('timeline_preview') or [])
    else:
        preview = list(timeline or [])
    pending: list[dict[str, Any]] = []
    for row in preview:
        if not isinstance(row, dict):
            continue
        if row.get('is_performed') or str(row.get('timeline_state') or '') == 'performed':
            continue
        if row_has_digital_pod_upload(row):
            pending.append(dict(row))
    if not pending:
        return {}
    pending.sort(
        key=lambda item: (
            int(item.get('sequence_number') or 0),
            str(item.get('log_date') or item.get('created_at') or ''),
        ),
    )
    return dict(pending[0])


def find_allowed_action_row_by_impact(
    allowed_actions: list[Any] | None,
    impact_key: str,
) -> dict[str, Any]:
    key = (impact_key or '').strip()
    if not key:
        return {}
    for row in allowed_actions or []:
        if not isinstance(row, dict):
            continue
        req = dict(row.get('execution_requirements') or {})
        if req.get(key) is True:
            return dict(row)
    return {}


def resolve_hard_copy_action_code_from_context(
    *,
    pod_cod: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
) -> str:
    block = dict((pod_cod or {}).get('hard_copy_confirmation') or {})
    for key in ('execute_action_code', 'action_code'):
        code = (block.get(key) or '').strip()
        if code:
            return code
    row = find_allowed_action_row_by_impact(
        list((workflow or {}).get('allowed_actions') or []),
        'hard_copy_collection',
    )
    code = (row.get('action_code') or '').strip()
    if code:
        return code
    return resolve_hard_copy_pod_action_code(tenant_schema)


def resolve_digital_pod_action_code_from_context(
    *,
    pod_cod: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
    timeline: dict[str, Any] | None = None,
) -> str:
    block = dict((pod_cod or {}).get('digital_evidence') or {})
    for key in ('execute_action_code', 'action_code'):
        code = (block.get(key) or '').strip()
        if code:
            return code
    row = find_pod_upload_row_in_allowed(
        list((workflow or {}).get('allowed_actions') or []),
    )
    if not row:
        row = find_pod_upload_row_in_timeline(
            timeline
            or (workflow or {}).get('timeline_preview')
            or (workflow or {}).get('timeline'),
        )
    if not row:
        row = find_allowed_action_row_by_impact(
            list((workflow or {}).get('allowed_actions') or []),
            'auto_pod_post',
        )
    code = (row.get('action_code') or '').strip()
    if code:
        return code
    primary = dict((workflow or {}).get('primary_action') or {})
    if row_has_digital_pod_upload(primary):
        code = (primary.get('action_code') or '').strip()
        if code:
            return code
    return resolve_digital_pod_action_code(tenant_schema)


def _find_workflow_row_by_action_code(
    workflow: dict[str, Any] | None,
    action_code: str,
) -> dict[str, Any]:
    code = (action_code or '').strip().upper()
    if not code:
        return {}
    wf = dict(workflow or {})
    for row in wf.get('allowed_actions') or []:
        if isinstance(row, dict) and str(row.get('action_code') or '').strip().upper() == code:
            return dict(row)
    for key in ('next_action', 'primary_action'):
        row = dict(wf.get(key) or {})
        if str(row.get('action_code') or '').strip().upper() == code:
            return row
    return {}


def _lookup_operation_action(action_code: str, tenant_schema: str) -> Any | None:
    code = (action_code or '').strip()
    schema = (tenant_schema or '').strip()
    if not code or not schema:
        return None
    with schema_context(schema):
        from tenant_workspace.models import TenantOperationAction

        return (
            TenantOperationAction.objects.exclude(
                status=TenantOperationAction.Status.INACTIVE,
            )
            .filter(action_code__iexact=code)
            .first()
        )


def action_code_is_digital_pod_upload(
    action_code: str | None,
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
) -> bool:
    """True when ``action_code`` is tenant Upload POD (digital), not hard-copy custody."""
    code = (action_code or '').strip()
    if not code:
        return False
    row = _find_workflow_row_by_action_code(workflow, code)
    if row and row_has_digital_pod_upload(row) and not row_has_hard_copy_collection(row):
        return True
    action = _lookup_operation_action(code, tenant_schema)
    if action is not None:
        if bool(getattr(action, 'auto_pod_post', False)):
            return True
        if is_hard_pod_action(action) and not getattr(action, 'auto_pod_post', False):
            return False
        return is_pod_upload_action(action)
    stub = _row_as_operation_action({'action_code': code})
    return is_pod_upload_action(stub) and not is_hard_pod_action(stub)


def action_code_is_hard_copy_custody(
    action_code: str | None,
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
) -> bool:
    """True when ``action_code`` is hard-copy POD custody / promotion."""
    code = (action_code or '').strip()
    if not code:
        return False
    row = _find_workflow_row_by_action_code(workflow, code)
    if row and row_has_hard_copy_collection(row):
        return True
    action = _lookup_operation_action(code, tenant_schema)
    if action is not None:
        if bool(getattr(action, 'hard_copy_collection', False)):
            return True
        return is_hard_pod_action(action) and not bool(getattr(action, 'auto_pod_post', False))
    stub = _row_as_operation_action({'action_code': code})
    return is_hard_pod_action(stub) and not bool(getattr(stub, 'auto_pod_post', False))
