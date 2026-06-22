"""
mobile_api/job_detail/services/job_detail_status_reconciler.py

Read-only workflow reconciliation for explicit Job Detail scope.

Reuses dashboard reconciliation primitives (log-primary, drift metadata) without
dashboard *selection* orchestration.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from mobile_api.dashboard.services.dashboard_status_reconciler import (
    _aggregate_workflow_integrity,
    _slice_reconciled_state,
    build_reconciliation_version,
)
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.guards.ownership import driver_pk
from mobile_api.job_detail.services.job_detail_projection_cache import (
    JobDetailProjectionCache,
    get_projection_cache,
    load_projection_cache,
)

from mobile_api.job_detail.services.job_detail_pod_cod_reconciler import (
    reconcile_job_detail_pod_cod,
)

from iroad_tenants.operation_runtime.workflow_state_reconciler import (
    reconcile_movement_execution_state,
    reconcile_shipment_execution_state,
)


def reconcile_job_detail_entities(
    context: JobDetailContext,
    *,
    request: Any | None = None,
    projection_cache: JobDetailProjectionCache | None = None,
) -> dict[str, Any]:
    """
    Populate ``context.reconciliation`` from Action Logs (bounded scan).

    No ORM writes — overlays authoritative status in-memory for workflow engine only.
    """
    _ = request
    driver_id = driver_pk(context.driver)
    cache = projection_cache or get_projection_cache(context) or load_projection_cache(
        context
    )

    bundle: dict[str, Any] = {
        'workflow_reconciled': True,
        'any_drift': False,
        'job_type': context.job_type,
        'shipment': None,
        'movement': None,
        'pod_cod': {},
        'compliance_integrity': {},
        'workflow_integrity': {},
        'reconciliation_version': '',
    }

    ship_logs = cache.shipment_logs if cache else None
    mov_logs = cache.movement_logs if cache else None

    if context.job_type == 'shipment' and context.shipment is not None:
        raw = reconcile_shipment_execution_state(
            context.shipment,
            movement=None,
            driver_id=driver_id,
            prefetched_logs=ship_logs,
        )
        state = _slice_reconciled_state(raw)
        state['raw'] = raw
        bundle['shipment'] = state
        if state.get('drift_detected'):
            bundle['any_drift'] = True
        wi = state.get('workflow_integrity') or {}
        if wi.get('missing_log_warning') or wi.get('fallback_to_columns'):
            bundle['any_drift'] = True

    if context.job_type == 'movement' and context.movement is not None:
        raw_m = reconcile_movement_execution_state(
            context.movement,
            driver_id=driver_id,
            prefetched_logs=mov_logs,
        )
        state_m = _slice_reconciled_state(raw_m)
        state_m['raw'] = raw_m
        bundle['movement'] = state_m
        if state_m.get('drift_detected'):
            bundle['any_drift'] = True
        wi = state_m.get('workflow_integrity') or {}
        if wi.get('missing_log_warning') or wi.get('fallback_to_columns'):
            bundle['any_drift'] = True

    if context.job_type == 'shipment' and context.shipment is not None:
        from iroad_tenants.operation_runtime.side_effects import (
            maybe_advance_delivered_when_job_close_ready,
        )

        if maybe_advance_delivered_when_job_close_ready(context.shipment):
            if hasattr(context.shipment, 'refresh_from_db'):
                context.shipment.refresh_from_db(
                    fields=['shipment_status', 'updated_at'],
                )
        pod_bundle = reconcile_job_detail_pod_cod(context)
        bundle['pod_cod'] = pod_bundle
        bundle['compliance_integrity'] = dict(
            pod_bundle.get('compliance_integrity') or {}
        )
        if bundle['compliance_integrity'].get('compliance_drift'):
            bundle['any_drift'] = True

    bundle['workflow_integrity'] = _aggregate_workflow_integrity(bundle)
    bundle['reconciliation_version'] = build_reconciliation_version(bundle)
    context.reconciliation = bundle
    return bundle


def entity_reconciliation_block(context: JobDetailContext) -> dict[str, Any]:
    """Active entity reconcile slice (shipment or movement) for workflow projection."""
    recon = context.reconciliation or {}
    if context.job_type == 'shipment':
        return dict(recon.get('shipment') or {})
    return dict(recon.get('movement') or {})


def authoritative_entity_status(context: JobDetailContext) -> str:
    block = entity_reconciliation_block(context)
    return (block.get('authoritative_status') or '').strip()


@contextmanager
def apply_reconciled_status_overlays(
    context: JobDetailContext,
) -> Iterator[None]:
    """
    In-memory status overlay so ``get_allowed_actions`` uses log-primary state.

    Restores column values after workflow projection (no DB mutation).
    """
    snapshots: list[tuple[Any, str, Any]] = []
    block = entity_reconciliation_block(context)

    try:
        auth = (block.get('authoritative_status') or '').strip()
        if not auth:
            auth = (block.get('column_status') or '').strip()
        if not auth:
            yield
            return

        if context.job_type == 'shipment' and context.shipment is not None:
            s = context.shipment
            snapshots.append((s, 'shipment_status', getattr(s, 'shipment_status', None)))
            setattr(s, 'shipment_status', auth)
        elif context.job_type == 'movement' and context.movement is not None:
            m = context.movement
            snapshots.append((m, 'status', getattr(m, 'status', None)))
            setattr(m, 'status', auth)
        yield
    finally:
        for obj, attr, prior in snapshots:
            setattr(obj, attr, prior)
