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
    return action_code_from_action(
        resolve_hard_copy_pod_action(tenant_schema),
        fallback=CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE,
    )


def row_has_hard_copy_collection(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    req = dict(row.get('execution_requirements') or {})
    if req.get('hard_copy_collection') is True:
        return True
    code = str(row.get('action_code') or '').strip().upper()
    return code == CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE


def row_has_digital_pod_upload(row: dict[str, Any] | None) -> bool:
    """True for digital POD upload, including combined Upload POD (digital + hard copy)."""
    if not row:
        return False
    req = dict(row.get('execution_requirements') or {})
    if req.get('auto_pod_post') is True:
        return True
    code = str(row.get('action_code') or '').strip().upper()
    return code == CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE


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
) -> str:
    block = dict((pod_cod or {}).get('digital_evidence') or {})
    for key in ('execute_action_code', 'action_code'):
        code = (block.get(key) or '').strip()
        if code:
            return code
    row = find_allowed_action_row_by_impact(
        list((workflow or {}).get('allowed_actions') or []),
        'auto_pod_post',
    )
    code = (row.get('action_code') or '').strip()
    if code:
        return code
    return resolve_digital_pod_action_code(tenant_schema)
