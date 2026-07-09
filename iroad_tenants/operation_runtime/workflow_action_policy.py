"""
Dynamic job-workflow action selection for mobile timeline and allowed-actions.

Timeline steps come from tenant Operation Action Master (``sequence_category=job``),
not hardcoded A1–A10 catalog rows. ``condition_code`` and impact flags drive COD-only
steps such as Payment Collection.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

from iroad_tenants.operation_runtime.impacts import (
    operation_action_matches,
    resolve_shipment_status_impact,
)
from iroad_tenants.operation_runtime.movement_action_validator import (
    is_empty_move_catalog_action,
)
from iroad_tenants.status_impact_resolution import resolve_booking_status_impact
from tenant_workspace.models import TenantOperationAction, TenantShipment

JOB_CLOSE_LABEL_NEEDLES = (
    'end job',
    'job closed',
    'close job',
    'job close',
)


def _bool_field(action: Any | None, field_name: str) -> bool:
    return getattr(action, field_name, False) is True


def _normalized_action_code(action: Any | None) -> str:
    return (getattr(action, 'action_code', '') or '').strip().upper()


def _action_code_in(action: Any | None, *codes: str) -> bool:
    code = _normalized_action_code(action)
    return code in {str(raw or '').strip().upper() for raw in codes if str(raw or '').strip()}


def action_requires_cod_order_type(action: Any | None) -> bool:
    """True when the action applies only to COD shipments (Payment Collection, etc.)."""
    if action is None:
        return False
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    if is_pod_upload_action(action):
        return False
    if action_is_job_close(action):
        return False
    condition = (getattr(action, 'condition_code', '') or '').strip().casefold()
    if condition and 'cod' in condition and 'order_type' in condition:
        return True
    if _bool_field(action, 'auto_treasury_post'):
        return True
    if _action_code_in(action, 'A9', 'OA-0009', 'OA-0010'):
        return True
    return operation_action_matches(
        action,
        'collect payment',
        'payment collection',
        'cod payment',
        'action 9',
    )


def action_is_start_job(action: Any | None) -> bool:
    if action is None:
        return False
    if _action_code_in(action, 'A1', 'OA-0001'):
        return True
    if _bool_field(action, 'auto_movement_post'):
        seq = int(getattr(action, 'sequence_number', 0) or 0)
        if seq <= 1:
            return True
    return operation_action_matches(action, 'start job', 'action 1')


def _booking_impact_is_executed(action: Any | None) -> bool:
    if action is None:
        return False
    raw = (getattr(action, 'booking_status_impact', '') or '').strip()
    if not raw:
        return False
    return resolve_booking_status_impact(raw) == 'completed'


def action_is_job_close(action: Any | None) -> bool:
    """
    True for End Job / Job Closed rows — by shipment Closed, booking Executed, or label.
    """
    if action is None:
        return False
    shipment_impact = resolve_shipment_status_impact(
        (getattr(action, 'shipment_status_impact', '') or '').strip(),
    )
    if shipment_impact == TenantShipment.ShipmentStatus.CLOSED:
        return True
    if _booking_impact_is_executed(action):
        return True
    label = (
        f'{(getattr(action, "action_code", "") or "")} '
        f'{(getattr(action, "english_label", "") or "")}'
    ).casefold()
    return any(needle in label for needle in JOB_CLOSE_LABEL_NEEDLES)


def job_close_action_q() -> Q:
    """ORM filter for tenant-configured job-close Operation Actions."""
    closed_tokens = (
        TenantShipment.ShipmentStatus.CLOSED,
        'Closed',
        'closed',
    )
    q = Q(shipment_status_impact__in=closed_tokens)
    q |= Q(booking_status_impact__iexact='Executed')
    q |= Q(booking_status_impact__iexact='executed')
    for needle in JOB_CLOSE_LABEL_NEEDLES:
        q |= Q(english_label__icontains=needle)
    return q


def pod_workflow_action_q() -> Q:
    """Tenant POD upload rows — flag or English label (always shown on timeline)."""
    q = Q(auto_pod_post=True)
    q |= Q(english_label__icontains='pod')
    q |= Q(english_label__icontains='proof of delivery')
    q |= Q(english_label__icontains='upload pod')
    return q


def cod_payment_action_q() -> Q:
    """Payment Collection — COD shipments only."""
    q = Q(auto_treasury_post=True)
    q |= Q(english_label__icontains='collect payment')
    q |= Q(english_label__icontains='payment collection')
    q |= Q(action_code__iexact='A9')
    q |= Q(action_code__iexact='OA-0009')
    return q


def resolve_job_close_operation_action() -> TenantOperationAction | None:
    """Resolve the active tenant End Job row (any code / label)."""
    row = (
        TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
        )
        .filter(job_close_action_q())
        .order_by('-sequence_number', 'action_code')
        .first()
    )
    if row is not None:
        return row
    for legacy_code in ('A10', 'OA-0010', 'OA-0011'):
        legacy = TenantOperationAction.objects.filter(
            action_code__iexact=legacy_code,
            status=TenantOperationAction.Status.ACTIVE,
        ).first()
        if legacy is not None and action_is_job_close(legacy):
            return legacy
    return None


def mobile_job_workflow_actions_queryset() -> QuerySet:
    """Active, driver-visible job workflow rows ordered for timeline display."""
    return (
        TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
            action_scope='job',
            sequence_category__iexact='job',
            mobile_visible=True,
            admin_only=False,
        )
        .order_by('sequence_number', 'action_code')
    )


def filter_shipment_timeline_workflow_actions(
    actions: list[Any],
    *,
    is_booking_job: bool,
    is_cod: bool,
    exclude_standalone_hard_copy: bool = True,
) -> list[Any]:
    """
    Keep tenant-configured job workflow steps applicable to this shipment/booking job.

    - Shipment jobs hide Start Job (logged on booking / movement bootstrap).
    - Credit jobs hide COD-only steps (Payment Collection).
  - Empty-move and standalone hard-copy rows are never timeline steps.
    """
    from iroad_tenants.operation_execution import _is_standalone_hard_copy_collection_action

    filtered: list[Any] = []
    for action in actions:
        if is_empty_move_catalog_action(action):
            continue
        if not is_booking_job and action_is_start_job(action):
            continue
        if (not is_cod) and action_requires_cod_order_type(action):
            continue
        if exclude_standalone_hard_copy and _is_standalone_hard_copy_collection_action(
            action,
        ):
            continue
        filtered.append(action)
    return filtered


def filter_empty_move_timeline_workflow_actions(actions: list[Any]) -> list[Any]:
    return [action for action in actions if is_empty_move_catalog_action(action)]


def empty_move_workflow_actions_queryset() -> QuerySet:
    return (
        TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
            action_scope='job',
            sequence_category__iexact='empty_move',
            mobile_visible=True,
            admin_only=False,
        )
        .order_by('sequence_number', 'action_code')
    )


def normalize_workflow_action_label(action: Any | None) -> str:
    return (getattr(action, 'english_label', None) or '').strip().casefold()


def shipment_applicable_workflow_actions(
    *,
    is_cod: bool,
    is_booking_job: bool = False,
) -> list[Any]:
    """Tenant job-workflow rows applicable to this shipment/booking context."""
    return filter_shipment_timeline_workflow_actions(
        list(mobile_job_workflow_actions_queryset()),
        is_booking_job=is_booking_job,
        is_cod=is_cod,
    )


def workflow_step_completed_on_shipment(
    step_action: Any | None,
    *,
    shipment,
    executed_action_ids: set,
    exclude_log_id=None,
) -> bool:
    """
    Whether a workflow step is done — by action log, semantic milestone, or label.
    """
    if step_action is None or shipment is None:
        return True

    step_id = getattr(step_action, 'action_id', None)
    if step_id and step_id in (executed_action_ids or set()):
        return True

    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        _shipment_pickup_loading_done,
        is_departure_action,
        is_delivery_arrival_action,
        is_loading_action,
        is_loading_completed_action,
        is_pickup_action,
        is_unloading_action,
        is_unloading_completed_action,
        shipment_departure_done,
        shipment_delivery_arrival_done,
        shipment_loading_completed_done,
        shipment_pod_upload_log_is_valid,
        shipment_unloading_completed_done,
        shipment_unloading_done,
        _shipment_logs_for_milestones,
    )

    if is_pickup_action(step_action):
        pickup_done, _loading_done = _shipment_pickup_loading_done(
            shipment,
            exclude_log_id=exclude_log_id,
        )
        return pickup_done
    if is_loading_action(step_action):
        _pickup_done, loading_done = _shipment_pickup_loading_done(
            shipment,
            exclude_log_id=exclude_log_id,
        )
        return loading_done
    if is_loading_completed_action(step_action):
        return shipment_loading_completed_done(
            shipment,
            exclude_log_id=exclude_log_id,
        )
    if is_departure_action(step_action):
        return shipment_departure_done(
            shipment,
            exclude_log_id=exclude_log_id,
        )
    if is_delivery_arrival_action(step_action):
        return shipment_delivery_arrival_done(
            shipment,
            exclude_log_id=exclude_log_id,
        )
    if is_unloading_action(step_action):
        return shipment_unloading_done(
            shipment,
            exclude_log_id=exclude_log_id,
        )
    if is_unloading_completed_action(step_action):
        return shipment_unloading_completed_done(
            shipment,
            exclude_log_id=exclude_log_id,
        )
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    if is_pod_upload_action(step_action) or _bool_field(step_action, 'auto_pod_post'):
        from iroad_tenants.operation_field_catalog import (
            operation_shipment_uses_hard_copy_pod,
        )

        if operation_shipment_uses_hard_copy_pod(shipment):
            from mobile_api.dashboard.selectors.pod_cod_policy import (
                is_hard_pod_custody_complete,
            )
            from iroad_tenants.operation_runtime.side_effects import (
                _mobile_log_evidence_for_shipment,
            )

            evidence = _mobile_log_evidence_for_shipment(shipment)
            if is_hard_pod_custody_complete(
                shipment,
                log_evidence=evidence,
            ):
                return bool(evidence.get('pod_uploaded')) or shipment_pod_upload_log_is_valid(
                    shipment,
                    exclude_log_id=exclude_log_id,
                )
        return shipment_pod_upload_log_is_valid(
            shipment,
            exclude_log_id=exclude_log_id,
        )
    if action_requires_cod_order_type(step_action):
        return (
            getattr(shipment, 'collection_status', None) or ''
        ).strip() == TenantShipment.CollectionStatus.COLLECTED

    label = normalize_workflow_action_label(step_action)
    if label:
        for log in _shipment_logs_for_milestones(
            shipment,
            exclude_log_id=exclude_log_id,
        ):
            logged = getattr(log, 'operation_action', None)
            if logged is not None and normalize_workflow_action_label(logged) == label:
                return True
    return False


def shipment_workflow_sequence_prerequisites_met(
    action: Any | None,
    *,
    shipment,
    executed_action_ids: set | None = None,
    exclude_log_id=None,
    is_booking_job: bool = False,
) -> bool:
    """
    Every earlier job-workflow step (lower ``sequence_number``) must be complete.
    """
    if action is None or shipment is None:
        return True
    if is_empty_move_catalog_action(action):
        return True

    is_cod = (getattr(shipment, 'order_type', None) or '').strip().upper() == 'COD'
    workflow = shipment_applicable_workflow_actions(
        is_cod=is_cod,
        is_booking_job=is_booking_job,
    )
    if not workflow:
        return True

    action_seq = int(getattr(action, 'sequence_number', 0) or 0)
    action_id = getattr(action, 'action_id', None)
    executed = executed_action_ids or set()

    for prior in workflow:
        if getattr(prior, 'action_id', None) == action_id:
            continue
        prior_seq = int(getattr(prior, 'sequence_number', 0) or 0)
        if prior_seq >= action_seq:
            continue
        if not workflow_step_completed_on_shipment(
            prior,
            shipment=shipment,
            executed_action_ids=executed,
            exclude_log_id=exclude_log_id,
        ):
            return False
    return True
