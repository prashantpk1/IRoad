"""
mobile_api/execution/services/execution_context_adapter.py

Bridge ``ExecuteActionContext`` ↔ ``JobDetailContext`` for read-only job_detail primitives.
"""
from __future__ import annotations

from typing import Any

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext


def to_job_detail_context(context: ExecuteActionContext) -> JobDetailContext:
    """
    Build a Job Detail orchestration context sharing the same resolved entities.

    Used for projection cache, reconciliation, and workflow (log-primary overlays).
    """
    return JobDetailContext(
        driver=context.driver,
        tenant_schema=context.tenant_schema,
        user_id=context.user_id,
        job_type=context.job_type,
        job_id=context.job_id,
        shipment=context.shipment,
        movement=context.movement,
        booking=context.booking,
        resolver_meta=dict(context.resolver_meta or {}),
        projection_cache=context.projection_cache,
        reconciliation=dict(context.reconciliation or {}),
        workflow=dict(context.workflow or {}),
        pod_cod=dict(context.pod_cod or {}),
        round_trip=dict(context.round_trip or {}),
        timeline=dict(context.timeline or {}),
        alerts=dict(context.alerts or {}),
        sync_metadata=dict(context.sync_metadata or {}),
        latest_action_log_id=getattr(context, 'latest_action_log_id', '') or '',
    )


def sync_from_job_detail(
    execute_context: ExecuteActionContext,
    job_detail_context: JobDetailContext,
) -> None:
    """Copy reconciliation / projection fields back to execute context."""
    execute_context.projection_cache = job_detail_context.projection_cache
    execute_context.reconciliation = dict(job_detail_context.reconciliation or {})
    execute_context.workflow = dict(job_detail_context.workflow or {})
    execute_context.pod_cod = dict(job_detail_context.pod_cod or {})
    execute_context.round_trip = dict(job_detail_context.round_trip or {})
    execute_context.timeline = dict(job_detail_context.timeline or {})
    execute_context.alerts = dict(job_detail_context.alerts or {})
    execute_context.sync_metadata = dict(job_detail_context.sync_metadata or {})
    execute_context.job = dict(getattr(job_detail_context, 'job_header', None) or {})
    execute_context.latest_action_log_id = (
        getattr(job_detail_context, 'latest_action_log_id', '') or ''
    )
    execute_context.content_hash = getattr(job_detail_context, 'content_hash', '') or ''


def _attach_shipment_to_execute_context(
    context: ExecuteActionContext,
    shipment: Any,
    *,
    redirect_meta_key: str,
) -> bool:
    """Point execute context at a resolved shipment leg."""
    ship_id = str(
        getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None) or ''
    ).strip()
    if not ship_id:
        return False

    booking = context.booking or getattr(shipment, 'booking', None)
    context.job_type = 'shipment'
    context.job_id = ship_id
    context.shipment = shipment
    if booking is not None:
        context.booking = booking

    meta = dict(getattr(context, 'resolver_meta', None) or {})
    meta[redirect_meta_key] = True
    context.resolver_meta = meta

    cache = getattr(context, '_execution_projection_cache', None)
    if cache is not None and hasattr(cache, 'reset_job_detail_scope'):
        cache.reset_job_detail_scope()
    return True


def _resolve_shipment_from_hard_pod_submission(
    *,
    tenant_schema: str,
    driver: Any | None,
    payload: dict[str, Any],
) -> Any | None:
    """Resolve shipment from Hard POD custody payload when booking pivot missed."""
    custody_submission_id = str(payload.get('custody_submission_id') or '').strip()
    client_submission_id = str(payload.get('client_submission_id') or '').strip()
    if not custody_submission_id and not client_submission_id:
        return None

    try:
        from mobile_api.hard_pod.models import HardPODCustodySubmission
        from mobile_api.job_detail.guards.entity_lookup import lookup_shipment_by_reference
    except ImportError:
        return None

    schema = (tenant_schema or '').strip()
    driver_id = str(
        getattr(driver, 'pk', None) or getattr(driver, 'driver_id', '') or ''
    ).strip()
    if not schema or not driver_id:
        return None

    submission = None
    if custody_submission_id:
        submission = (
            HardPODCustodySubmission.objects.filter(
                tenant_schema=schema,
                driver_id=driver_id,
                pk=custody_submission_id,
            )
            .first()
        )
    if submission is None and client_submission_id:
        submission = (
            HardPODCustodySubmission.objects.filter(
                tenant_schema=schema,
                driver_id=driver_id,
                client_submission_id=client_submission_id,
            )
            .order_by('-submitted_at')
            .first()
        )
    if submission is None:
        return None

    shipment_ref = str(getattr(submission, 'shipment_id', '') or '').strip()
    if not shipment_ref:
        return None
    return lookup_shipment_by_reference(shipment_ref)


def _repair_delivered_shipment_for_hard_pod(shipment: Any | None) -> None:
    """Rewind Delivered → POD Submitted when hard-copy custody is still due."""
    if shipment is None:
        return
    try:
        from iroad_tenants.operation_runtime.latest_state import (
            repair_delivered_before_hard_pod_custody,
        )

        repair_delivered_before_hard_pod_custody(shipment)
    except Exception:
        return


def _shipment_pk(shipment: Any | None) -> str:
    if shipment is None:
        return ''
    return str(
        getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None) or ''
    ).strip()


def finalize_execute_scope(context: ExecuteActionContext) -> bool:
    """
    Apply late scope pivots and shipment repairs before projection / stale checks.

    Idempotent per request — safe to call from prepare and validation.
    """
    if getattr(context, '_execute_scope_finalized', False):
        return False
    changed = ensure_shipment_execute_context(context)
    context._execute_scope_finalized = True  # type: ignore[attr-defined]
    return changed


def ensure_shipment_execute_context(context: ExecuteActionContext) -> bool:
    """
    Attach shipment scope before shipment-phase execute validation.

    Booking-scoped execute (dashboard cards) must pivot to the driver's active
    leg or resolve from Hard POD custody before POD / hard-copy policy runs.
    """
    changed = False
    payload = dict(getattr(context, 'payload', None) or {})

    custody_shipment = _resolve_shipment_from_hard_pod_submission(
        tenant_schema=context.tenant_schema,
        driver=context.driver,
        payload=payload,
    )
    if custody_shipment is not None:
        custody_pk = _shipment_pk(custody_shipment)
        current_pk = _shipment_pk(context.shipment)
        if custody_pk and custody_pk != current_pk:
            changed = _attach_shipment_to_execute_context(
                context,
                custody_shipment,
                redirect_meta_key='hard_pod_custody_shipment_redirect',
            ) or changed

    if context.shipment is not None and context.driver is not None:
        from mobile_api.helpers.backload_booking_redirect import (
            coerce_driver_active_shipment_leg,
            ensure_active_round_trip_scope,
        )

        coerced = coerce_driver_active_shipment_leg(context.driver, context.shipment)
        coerced_pk = _shipment_pk(coerced)
        current_pk = _shipment_pk(context.shipment)
        if coerced_pk and coerced_pk != current_pk and coerced is not None:
            changed = _attach_shipment_to_execute_context(
                context,
                coerced,
                redirect_meta_key='closed_shipment_active_leg_redirect',
            ) or changed
        elif context.booking is not None:
            changed = ensure_active_round_trip_scope(context) or changed

    if context.shipment is not None:
        _repair_delivered_shipment_for_hard_pod(context.shipment)
        return changed

    if context.booking is not None and context.driver is not None:
        from mobile_api.helpers.backload_booking_redirect import (
            pivot_booking_to_active_shipment,
        )

        if pivot_booking_to_active_shipment(
            driver=context.driver,
            booking=context.booking,
            context=context,
        ):
            _repair_delivered_shipment_for_hard_pod(context.shipment)
            return True

    payload = dict(getattr(context, 'payload', None) or {})
    shipment = _resolve_shipment_from_hard_pod_submission(
        tenant_schema=context.tenant_schema,
        driver=context.driver,
        payload=payload,
    )
    if shipment is None:
        return False
    _repair_delivered_shipment_for_hard_pod(shipment)
    return _attach_shipment_to_execute_context(
        context,
        shipment,
        redirect_meta_key='hard_pod_custody_shipment_redirect',
    )


def pivot_execute_context_for_round_trip_continuation(
    context: ExecuteActionContext,
) -> bool:
    """
    After outbound leg completes, align post-execute read model with return leg.

    Prevents stale closed-outbound job detail when the driver presses Back.
    """
    if context.booking is None or context.driver is None:
        return False
    shipment = context.shipment
    if shipment is None:
        return False
    from mobile_api.dashboard.selectors import booking_selection_policy as policy
    from mobile_api.utils.next_action_hint_builder import (
        resolve_round_trip_continuation_open_job,
    )

    if not policy.is_shipment_business_complete(shipment):
        return False
    if resolve_round_trip_continuation_open_job(
        context.booking,
        driver=context.driver,
    ) is None:
        return False

    from mobile_api.helpers.backload_booking_redirect import (
        pivot_closed_shipment_to_active_leg,
        pivot_context_to_backload_booking,
    )

    if pivot_context_to_backload_booking(
        driver=context.driver,
        booking=context.booking,
        shipment=shipment,
        context=context,
    ):
        return True
    return pivot_closed_shipment_to_active_leg(
        driver=context.driver,
        booking=context.booking,
        shipment=shipment,
        context=context,
    )


def pivot_execute_context_to_born_shipment(
    context: ExecuteActionContext,
) -> bool:
    """
    After booking-scoped execute links a new shipment (Auto Shipment at A4), switch
    post-execute read model to shipment scope so workflow shows A5+ instead of
    stale booking-only actions (e.g. A8).
    """
    if context.job_type != 'booking':
        return False

    action_log = context.action_log
    shipment_ref = ''
    if action_log is not None:
        shipment_ref = str(
            getattr(action_log, 'shipment_id', None)
            or getattr(getattr(action_log, 'shipment', None), 'pk', None)
            or ''
        ).strip()
    if not shipment_ref:
        return False

    shipment = context.shipment
    ship_pk = ''
    if shipment is not None:
        ship_pk = str(
            getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None) or ''
        ).strip()
    if not ship_pk or ship_pk != shipment_ref:
        from mobile_api.job_detail.guards.entity_lookup import lookup_shipment_by_reference

        shipment = lookup_shipment_by_reference(shipment_ref)
    if shipment is None:
        return False

    ship_id = str(
        getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None) or ''
    ).strip()
    if not ship_id:
        return False

    context.job_type = 'shipment'
    context.job_id = ship_id
    context.shipment = shipment
    context.booking = getattr(shipment, 'booking', None) or context.booking

    cache = getattr(context, '_execution_projection_cache', None)
    if cache is not None and hasattr(cache, 'reset_job_detail_scope'):
        cache.reset_job_detail_scope()

    return True
