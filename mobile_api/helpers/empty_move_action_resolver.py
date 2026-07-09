"""
Resolve tenant Action Master codes for empty-move mobile workflow.

All workflow steps come from ``sequence_category = empty_move`` rows ordered by
``sequence_number`` — no hardcoded EM1–EM4 requirement at runtime.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django_tenants.utils import schema_context

from iroad_tenants.operation_runtime.movement_action_validator import (
    empty_move_sequence_category_q,
    is_empty_move_catalog_action,
)
from iroad_tenants.operation_runtime.movement_state_machine import (
    is_movement_arrived_action,
    is_movement_complete_action,
    is_movement_in_transit_action,
    is_movement_start_action,
)
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    action_code_from_action,
)
from tenant_workspace.models import TenantOperationAction

# Unit-test fallback only when no tenant schema / DB rows exist.
_LEGACY_FALLBACK_STEP_CODES = ('EM1', 'EM2', 'EM3', 'EM4')
_LEGACY_FALLBACK_STEP_LABELS = ('Pickup', 'In Transit', 'Delivery', 'Completed')


def _iter_empty_move_actions(tenant_schema: str):
    schema = (tenant_schema or '').strip()
    if not schema:
        return
    try:
        with schema_context(schema):
            yield from (
                TenantOperationAction.objects.exclude(
                    status=TenantOperationAction.Status.INACTIVE,
                )
                .filter(empty_move_sequence_category_q())
                .order_by('sequence_number', 'action_code')
            )
    except Exception as exc:
        from django.test.testcases import DatabaseOperationForbidden

        if isinstance(exc, DatabaseOperationForbidden):
            return
        raise


def list_empty_move_workflow_actions(tenant_schema: str = '') -> list[Any]:
    """Active empty-move Action Master rows in execution order."""
    return list(_iter_empty_move_actions(tenant_schema))


def _action_sort_key(action: Any) -> tuple[int, str]:
    return (
        int(getattr(action, 'sequence_number', 0) or 0),
        str(getattr(action, 'action_code', '') or ''),
    )


def _pick_action(actions: list[Any], matcher) -> Any | None:
    matched = [action for action in actions if matcher(action)]
    if not matched:
        return None
    return sorted(matched, key=_action_sort_key)[0]


def _step_key_for_action(action: Any, *, index: int) -> str:
    seq = int(getattr(action, 'sequence_number', 0) or 0)
    if seq > 0:
        return f'seq_{seq}'
    return f'step_{index + 1}'


def _parse_step_sequence(step_key: str) -> int | None:
    token = (step_key or '').strip().casefold()
    for prefix in ('seq_', 'step_'):
        if token.startswith(prefix):
            try:
                return int(token.split('_', 1)[1])
            except (IndexError, ValueError):
                return None
    return None


def _legacy_step_specs() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    legacy_keys = ('pickup', 'in_transit', 'delivery', 'complete')
    return tuple(
        (
            legacy_keys[index],
            label,
            (code,) if code else (),
        )
        for index, (label, code) in enumerate(
            zip(_LEGACY_FALLBACK_STEP_LABELS, _LEGACY_FALLBACK_STEP_CODES),
        )
    )


def resolve_empty_move_workflow_step_specs(
    tenant_schema: str = '',
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """
    One workflow row per tenant Action Master empty-move action (ordered).

    Returns tuples of ``(step_key, label, action_codes)``.
    """
    actions = list_empty_move_workflow_actions(tenant_schema)
    if not actions:
        if (tenant_schema or '').strip():
            return ()
        return _legacy_step_specs()

    specs: list[tuple[str, str, tuple[str, ...]]] = []
    for index, action in enumerate(actions):
        label = (
            (getattr(action, 'english_label', None) or '').strip()
            or str(getattr(action, 'action_code', '') or '').strip()
        )
        code = str(getattr(action, 'action_code', '') or '').strip()
        specs.append(
            (
                _step_key_for_action(action, index=index),
                label,
                (code,) if code else (),
            ),
        )
    return tuple(specs)


def resolve_empty_move_action_for_step(
    step_key: str,
    tenant_schema: str = '',
) -> Any | None:
    """Resolve tenant Action Master row for one workflow step key."""
    actions = list_empty_move_workflow_actions(tenant_schema)
    if not actions:
        return None

    target_seq = _parse_step_sequence(step_key)
    if target_seq is not None:
        for action in actions:
            seq = int(getattr(action, 'sequence_number', 0) or 0)
            if seq == target_seq:
                return action
        if step_key.startswith('step_'):
            try:
                index = int(step_key.split('_', 1)[1]) - 1
                if 0 <= index < len(actions):
                    return actions[index]
            except (IndexError, ValueError):
                pass

    legacy_matchers = {
        'pickup': is_movement_start_action,
        'in_transit': is_movement_in_transit_action,
        'delivery': is_movement_arrived_action,
        'complete': is_movement_complete_action,
    }
    matcher = legacy_matchers.get((step_key or '').strip().casefold())
    if matcher is not None:
        return _pick_action(actions, matcher)
    return None


def resolve_empty_move_start_action(tenant_schema: str) -> Any | None:
    actions = list_empty_move_workflow_actions(tenant_schema)
    if not actions:
        return None
    return _pick_action(actions, is_movement_start_action) or actions[0]


def resolve_empty_move_complete_action(tenant_schema: str) -> Any | None:
    actions = list_empty_move_workflow_actions(tenant_schema)
    if not actions:
        return None
    return _pick_action(actions, is_movement_complete_action) or actions[-1]


def resolve_empty_move_in_transit_action(tenant_schema: str) -> Any | None:
    actions = list_empty_move_workflow_actions(tenant_schema)
    if not actions:
        return None
    picked = _pick_action(actions, is_movement_in_transit_action)
    if picked is not None:
        return picked
    if len(actions) >= 2:
        return actions[1]
    return None


def resolve_empty_move_arrived_action(tenant_schema: str) -> Any | None:
    actions = list_empty_move_workflow_actions(tenant_schema)
    if not actions:
        return None
    picked = _pick_action(actions, is_movement_arrived_action)
    if picked is not None:
        return picked
    if len(actions) >= 3:
        return actions[-2]
    return None


def resolve_empty_move_start_action_code(tenant_schema: str) -> str:
    return action_code_from_action(
        resolve_empty_move_start_action(tenant_schema),
        fallback=_LEGACY_FALLBACK_STEP_CODES[0],
    )


def resolve_empty_move_complete_action_code(tenant_schema: str) -> str:
    action = resolve_empty_move_complete_action(tenant_schema)
    if action is not None:
        return action_code_from_action(action, fallback='')
    if not (tenant_schema or '').strip():
        return _LEGACY_FALLBACK_STEP_CODES[-1]
    return ''


def action_is_empty_move_lifecycle(action: Any | None) -> bool:
    """Any configured empty-move workflow action (not only EM lifecycle matchers)."""
    return is_empty_move_catalog_action(action)


def action_is_empty_move_terminal(action: Any | None, *, tenant_schema: str = '') -> bool:
    if action is None:
        return False
    terminal = resolve_empty_move_complete_action(tenant_schema)
    if terminal is not None:
        terminal_code = str(getattr(terminal, 'action_code', '') or '').strip().casefold()
        action_code = str(getattr(action, 'action_code', '') or '').strip().casefold()
        if terminal_code and action_code == terminal_code:
            return True
        terminal_id = getattr(terminal, 'action_id', None)
        action_id = getattr(action, 'action_id', None)
        if terminal_id and action_id and str(terminal_id) == str(action_id):
            return True
    return is_movement_complete_action(action)


def row_is_empty_move_action(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    req = dict(row.get('execution_requirements') or {})
    cat = str(
        req.get('sequence_category')
        or row.get('sequence_category')
        or row.get('action_category')
        or '',
    ).strip().casefold()
    if cat in {'empty_move', 'empty move'}:
        return True
    return action_is_empty_move_lifecycle(_row_as_action(row))


def _row_as_action(row: dict[str, Any]) -> SimpleNamespace:
    req = dict(row.get('execution_requirements') or {})
    return SimpleNamespace(
        action_code=row.get('action_code'),
        english_label=(
            row.get('english_label')
            or row.get('label')
            or row.get('execution_label')
            or row.get('action_name')
        ),
        arabic_label=row.get('arabic_label'),
        sequence_category=(
            req.get('sequence_category')
            or row.get('sequence_category')
            or row.get('action_category')
            or ''
        ),
        sequence_number=row.get('sequence_number') or req.get('sequence_number'),
        movement_status_impact=(
            req.get('movement_status_impact')
            or row.get('movement_status_impact')
            or ''
        ),
        shipment_status_impact=(
            req.get('shipment_status_impact')
            or row.get('shipment_status_impact')
            or ''
        ),
    )


def resolve_empty_move_terminal_step_spec(
    tenant_schema: str = '',
) -> tuple[str, str, tuple[str, ...]]:
    """Last workflow step spec (terminal / end-job action)."""
    specs = resolve_empty_move_workflow_step_specs(tenant_schema)
    if specs:
        return specs[-1]
    return _legacy_step_specs()[-1]


def empty_move_sequence_bounds(
    tenant_schema: str = '',
) -> tuple[int | None, int | None]:
    """Min/max ``sequence_number`` for active empty-move actions."""
    numbers = [
        int(getattr(row, 'sequence_number', 0) or 0)
        for row in list_empty_move_workflow_actions(tenant_schema)
        if int(getattr(row, 'sequence_number', 0) or 0) > 0
    ]
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def empty_move_route_endpoint_side(action: Any | None, *, tenant_schema: str = '') -> str | None:
    """
    GPS route stamping side for empty-move actions.

    First sequence step -> departure (``from``); last sequence step -> arrival (``to``).
  Legacy EM / label matchers apply when sequence metadata is unavailable.
    """
    if action is None:
        return None

    schema = (tenant_schema or '').strip()
    if not schema:
        from django.db import connection

        schema = str(getattr(connection, 'schema_name', '') or '').strip()
        if schema == 'public':
            schema = ''

    if is_empty_move_catalog_action(action):
        seq = int(getattr(action, 'sequence_number', 0) or 0)
        min_seq, max_seq = empty_move_sequence_bounds(schema)
        if min_seq is not None and max_seq is not None and seq > 0:
            if seq == min_seq:
                return 'from'
            if seq == max_seq:
                return 'to'
            return None

    if is_movement_start_action(action):
        return 'from'
    if is_movement_complete_action(action):
        return 'to'
    return None
