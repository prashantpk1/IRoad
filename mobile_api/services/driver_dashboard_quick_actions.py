"""
mobile_api/services/driver_dashboard_quick_actions.py

Lightweight dashboard shortcut metadata for mobile clients (Phase 1).

Not an execution engine — returns visibility, enabled state, labels, and future
route/API hints only. Business rules use ``counters`` + ``current_job`` snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from django.utils.translation import gettext as _

from mobile_api.rbac import request_has_capability

# Stable action identifiers (contract for mobile routing keys).
ACTION_CONTINUE_ACTIVE_JOB = 'continue_active_job'
ACTION_UPLOAD_POD = 'upload_pod'
ACTION_CREATE_EMPTY_MOVE = 'create_empty_move'
ACTION_COD_COLLECTION = 'cod_collection'
ACTION_ACTIVE_MOVEMENTS = 'active_movements'

PHASE_PLACEHOLDER = 'placeholder'
PHASE_ROUTE_HINT = 'route_hint'


@dataclass(frozen=True)
class QuickActionExecutionSpec:
    """Future deep-link / API integration (no server-side execution in Phase 1)."""

    phase: str
    route_key: str
    deep_link_template: str
    api_path: str | None = None
    http_method: str | None = None


@dataclass(frozen=True)
class QuickActionDefinition:
    """Static catalog row for one dashboard shortcut."""

    id: str
    label_msgid: str
    sort_order: int
    required_capabilities: tuple[str, ...]
    execution: QuickActionExecutionSpec
    evaluate: Callable[['QuickActionBuildContext'], tuple[bool, str | None]]


@dataclass
class QuickActionBuildContext:
    counters: dict[str, int]
    current_job: dict[str, Any]
    request: Any = None
    driver: Any = None
    ownership_scope: Any = None

    @property
    def has_active_job(self) -> bool:
        return bool(self.current_job.get('has_active_job'))

    @property
    def shipment_id(self) -> str | None:
        shipment = self.current_job.get('shipment') or {}
        return shipment.get('shipment_id') or self.current_job.get('shipment_id')

    @property
    def movement_id(self) -> str | None:
        movement = self.current_job.get('movement') or {}
        return movement.get('movement_id') or None

    def counter(self, key: str) -> int:
        return int(self.counters.get(key) or 0)


def _reason_msgid(reason_code: str | None) -> str | None:
    if not reason_code:
        return None
    return f'mobile.dashboard.action.reason.{reason_code}'


def _eval_continue(ctx: QuickActionBuildContext) -> tuple[bool, str | None]:
    if ctx.has_active_job:
        return True, None
    return False, 'no_active_job'


def _eval_upload_pod(ctx: QuickActionBuildContext) -> tuple[bool, str | None]:
    if not ctx.has_active_job:
        return False, 'no_active_job'
    if ctx.counter('pending_pod') > 0:
        return True, None
    pod = ctx.current_job.get('pod') or {}
    if pod.get('needs_attention'):
        return True, None
    return False, 'pod_not_pending'


def _eval_active_movements(ctx: QuickActionBuildContext) -> tuple[bool, str | None]:
    if ctx.counter('active_movements') > 0:
        return True, None
    return False, 'no_active_movement'


def _eval_cod(ctx: QuickActionBuildContext) -> tuple[bool, str | None]:
    if ctx.counter('cod_pending') > 0:
        return True, None
    cod = ctx.current_job.get('cod') or {}
    if cod.get('is_collection_pending'):
        return True, None
    return False, 'no_cod_pending'


def _eval_empty_move(_ctx: QuickActionBuildContext) -> tuple[bool, str | None]:
    return False, 'module_not_available'


QUICK_ACTION_REGISTRY: tuple[QuickActionDefinition, ...] = (
    QuickActionDefinition(
        id=ACTION_CONTINUE_ACTIVE_JOB,
        label_msgid='mobile.dashboard.action.continue_job',
        sort_order=10,
        required_capabilities=('mobile.driver.quick_action.continue_job',),
        execution=QuickActionExecutionSpec(
            phase=PHASE_ROUTE_HINT,
            route_key='current_job_detail',
            deep_link_template='/driver/jobs/active/{shipment_id}',
            api_path=None,
            http_method=None,
        ),
        evaluate=_eval_continue,
    ),
    QuickActionDefinition(
        id=ACTION_UPLOAD_POD,
        label_msgid='mobile.dashboard.action.upload_pod',
        sort_order=20,
        required_capabilities=('mobile.driver.quick_action.upload_pod',),
        execution=QuickActionExecutionSpec(
            phase=PHASE_ROUTE_HINT,
            route_key='shipment_pod_upload',
            deep_link_template='/driver/shipments/{shipment_id}/pod/upload',
            api_path='/api/v1/mobile/driver/shipments/{shipment_id}/pod/',
            http_method='POST',
        ),
        evaluate=_eval_upload_pod,
    ),
    QuickActionDefinition(
        id=ACTION_ACTIVE_MOVEMENTS,
        label_msgid='mobile.dashboard.action.active_movement',
        sort_order=30,
        required_capabilities=('mobile.driver.quick_action.active_movements',),
        execution=QuickActionExecutionSpec(
            phase=PHASE_ROUTE_HINT,
            route_key='active_movements_list',
            deep_link_template='/driver/movements/active',
            api_path='/api/v1/mobile/driver/movements/active/',
            http_method='GET',
        ),
        evaluate=_eval_active_movements,
    ),
    QuickActionDefinition(
        id=ACTION_COD_COLLECTION,
        label_msgid='mobile.dashboard.action.cod',
        sort_order=40,
        required_capabilities=('mobile.driver.quick_action.cod_collection',),
        execution=QuickActionExecutionSpec(
            phase=PHASE_ROUTE_HINT,
            route_key='cod_collection',
            deep_link_template='/driver/shipments/{shipment_id}/cod',
            api_path='/api/v1/mobile/driver/shipments/{shipment_id}/cod/',
            http_method='POST',
        ),
        evaluate=_eval_cod,
    ),
    QuickActionDefinition(
        id=ACTION_CREATE_EMPTY_MOVE,
        label_msgid='mobile.dashboard.action.empty_move',
        sort_order=50,
        required_capabilities=('mobile.driver.quick_action.empty_move',),
        execution=QuickActionExecutionSpec(
            phase=PHASE_PLACEHOLDER,
            route_key='empty_movement_create',
            deep_link_template='/driver/movements/empty/create',
            api_path='/api/v1/mobile/driver/movements/empty/',
            http_method='POST',
        ),
        evaluate=_eval_empty_move,
    ),
)


def _capability_visible(request, required: tuple[str, ...]) -> bool:
    if not required:
        return True
    if request is None:
        return False
    return all(request_has_capability(request, cap) for cap in required)


def _resolve_deep_link(template: str, ctx: QuickActionBuildContext) -> str:
    shipment_id = ctx.shipment_id or ''
    movement_id = ctx.movement_id or ''
    return (
        template.replace('{shipment_id}', shipment_id)
        .replace('{movement_id}', movement_id)
    )


def _resolve_api_path(template: str | None, ctx: QuickActionBuildContext) -> str | None:
    if not template:
        return None
    return _resolve_deep_link(template, ctx)


def project_quick_action(
    definition: QuickActionDefinition,
    ctx: QuickActionBuildContext,
) -> dict[str, Any] | None:
    """Build one action dict; return ``None`` when hidden by capability rules."""
    if not _capability_visible(ctx.request, definition.required_capabilities):
        return None

    enabled, reason_code = definition.evaluate(ctx)
    reason_msgid = _reason_msgid(reason_code)
    reason_message = str(_(reason_msgid)) if reason_msgid else None

    execution = {
        'phase': definition.execution.phase,
        'route_key': definition.execution.route_key,
        'deep_link': _resolve_deep_link(definition.execution.deep_link_template, ctx),
        'api_path': _resolve_api_path(definition.execution.api_path, ctx),
        'http_method': definition.execution.http_method,
    }

    payload: dict[str, Any] = {
        'id': definition.id,
        'label': str(_(definition.label_msgid)),
        'sort_order': definition.sort_order,
        'visible': True,
        'enabled': enabled,
        'reason_code': reason_code,
        'reason_message': reason_message,
        'required_capabilities': list(definition.required_capabilities),
        'execution': execution,
    }

    if ctx.driver is not None and ctx.shipment_id and enabled:
        scope = ctx.ownership_scope
        if scope is not None:
            owns = scope.owns_shipment(ctx.shipment_id)
        else:
            from mobile_api.helpers.dashboard_security import driver_owns_shipment_id

            owns = driver_owns_shipment_id(ctx.driver, ctx.shipment_id)
        if owns:
            payload['shipment_id'] = ctx.shipment_id
    if (
        ctx.driver is not None
        and ctx.movement_id
        and definition.id == ACTION_ACTIVE_MOVEMENTS
        and enabled
    ):
        scope = ctx.ownership_scope
        if scope is not None:
            owns = scope.owns_movement(ctx.movement_id)
        else:
            from mobile_api.helpers.dashboard_security import driver_owns_movement_id

            owns = driver_owns_movement_id(ctx.driver, ctx.movement_id)
        if owns:
            payload['movement_id'] = ctx.movement_id

    return payload


def build_dashboard_quick_actions(
    *,
    counters: dict[str, int],
    current_job: dict[str, Any],
    request=None,
    driver=None,
    ownership_scope=None,
) -> list[dict[str, Any]]:
    """
    Ordered list of visible quick actions for ``data.quick_actions``.

    Hidden actions (missing capability) are omitted from the payload.
    """
    ctx = QuickActionBuildContext(
        ownership_scope=ownership_scope,
        counters=counters,
        current_job=current_job,
        request=request,
        driver=driver,
    )
    items: list[dict[str, Any]] = []
    for definition in sorted(QUICK_ACTION_REGISTRY, key=lambda d: d.sort_order):
        row = project_quick_action(definition, ctx)
        if row is not None:
            items.append(row)
    return items


def build_quick_actions_meta(*, actions: list[dict[str, Any]]) -> dict[str, int]:
    """Compact counts for optional dashboard envelope fields."""
    enabled = sum(1 for a in actions if a.get('enabled'))
    return {
        'total_visible': len(actions),
        'total_enabled': enabled,
    }
