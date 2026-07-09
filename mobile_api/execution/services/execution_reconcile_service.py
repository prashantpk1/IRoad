"""
mobile_api/execution/services/execution_reconcile_service.py

Pre/post execute reconciliation — log-primary workflow state for validation.

Reuses job_detail projection cache, reconciler, overlays, and workflow projection.
No Action Log writes or ORM mutations (except post-execute reads refreshed state).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from mobile_api.execution.dto.authoritative_execution_context import (
    AuthoritativeExecutionContext,
)
from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.guards.execution_ownership_guard import ExecutionOwnershipGuard
from mobile_api.execution.services.execution_context_adapter import (
    finalize_execute_scope,
    pivot_execute_context_for_round_trip_continuation,
    pivot_execute_context_to_born_shipment,
    sync_from_job_detail,
    to_job_detail_context,
)
from mobile_api.execution.services.execution_projection_cache import (
    ExecutionProjectionCache,
)
from mobile_api.job_detail.guards.entity_lookup import (
    booking_entity_summary,
    movement_entity_summary,
    shipment_entity_summary,
)
from mobile_api.job_detail.services.job_detail_status_reconciler import (
    apply_reconciled_status_overlays,
    authoritative_entity_status,
    entity_reconciliation_block,
)


class ExecutionReconcileService:
    """
    Prepare authoritative pre-execute context: resolve → reconcile → overlay → workflow.

    Read-only — uses bounded Action Log scan and in-memory status overlays.
    """

    def __init__(
        self,
        *,
        ownership_guard: ExecutionOwnershipGuard | None = None,
    ) -> None:
        self._ownership_guard = ownership_guard or ExecutionOwnershipGuard()

    def prepare_pre_execute(
        self,
        context: ExecuteActionContext,
        *,
        request: Any | None = None,
    ) -> AuthoritativeExecutionContext:
        """
        Full pre-execute pipeline inside tenant schema.

        Single projection-cache load + reconcile + workflow + sync metadata.
        """
        self._ownership_guard.resolve_entity(context)
        finalize_execute_scope(context)
        self._ownership_guard.assert_driver_may_execute(context)

        projection = ExecutionProjectionCache.attach(context)
        projection.ensure_pre_execute_reconcile(request=request)
        projection.ensure_workflow(request=request)
        projection.ensure_sync_metadata(request=request)

        authoritative = self.build_authoritative_context(context)
        context.authoritative = dict(authoritative)
        return authoritative

    def reconcile_pre_execute(self, context: ExecuteActionContext) -> None:
        """Reconcile only — caller must have resolved entity already."""
        projection = ExecutionProjectionCache.attach(context)
        projection.ensure_pre_execute_reconcile()

    def reconcile_post_execute(
        self,
        context: ExecuteActionContext,
        *,
        request: Any | None = None,
    ) -> None:
        """
        Refresh workflow / pod_cod / timeline / alerts / sync after kernel or replay.

        One post-mutation projection pass (no duplicate log scans).
        """
        pivot_execute_context_to_born_shipment(context)
        pivot_execute_context_for_round_trip_continuation(context)
        projection = ExecutionProjectionCache.attach(context)
        projection.build_post_execute_sections(request=request)
        context.authoritative = dict(self.build_authoritative_context(context))

    @contextmanager
    def apply_status_overlays(
        self,
        context: ExecuteActionContext,
    ) -> Iterator[None]:
        """In-memory overlay so policy uses log-primary status (not column drift)."""
        job_detail_ctx = to_job_detail_context(context)
        with apply_reconciled_status_overlays(job_detail_ctx):
            yield

    def build_authoritative_context(
        self,
        context: ExecuteActionContext,
    ) -> AuthoritativeExecutionContext:
        """Map orchestration state to the canonical pre-execute contract."""
        job_detail_ctx = to_job_detail_context(context)
        reconciled_state = _public_reconciled_slice(job_detail_ctx)
        workflow = dict(context.workflow or {})
        entity = _build_entity_snapshot(context, reconciled_state)
        allowed_actions = list(workflow.get('allowed_actions') or [])

        return AuthoritativeExecutionContext(
            job_type=context.job_type,
            entity=entity,
            workflow=workflow,
            reconciled_state=reconciled_state,
            allowed_actions=allowed_actions,
            sync_metadata=dict(context.sync_metadata or {}),
        )


def _public_reconciled_slice(job_detail_ctx: Any) -> dict[str, Any]:
    block = dict(entity_reconciliation_block(job_detail_ctx))
    block.pop('raw', None)
    return {
        'authoritative_status': (block.get('authoritative_status') or '').strip(),
        'column_status': (block.get('column_status') or '').strip(),
        'status_source': (block.get('status_source') or '').strip(),
        'drift_detected': bool(block.get('drift_detected')),
        'drift_reason': (block.get('drift_reason') or '').strip(),
        'workflow_integrity': dict(block.get('workflow_integrity') or {}),
        'latest_action_log_id': (
            getattr(job_detail_ctx, 'latest_action_log_id', '') or ''
        ).strip(),
    }


def _build_entity_snapshot(
    context: ExecuteActionContext,
    reconciled_state: dict[str, Any],
) -> dict[str, Any]:
    """Entity identity with reconciled status surfaced for execute validation."""
    auth_status = (reconciled_state.get('authoritative_status') or '').strip()
    meta_entity = dict((context.resolver_meta or {}).get('entity') or {})

    if context.job_type == 'shipment' and context.shipment is not None:
        base = shipment_entity_summary(context.shipment)
        if auth_status:
            base['shipment_status'] = auth_status
            base['status_authority'] = 'action_log'
        elif meta_entity:
            base.update({k: v for k, v in meta_entity.items() if k not in base})
        return base

    if context.job_type == 'booking' and context.booking is not None:
        base = booking_entity_summary(context.booking)
        if auth_status:
            base['booking_status'] = auth_status
            base['status_authority'] = 'action_log'
        elif meta_entity:
            base.update({k: v for k, v in meta_entity.items() if k not in base})
        return base

    if context.movement is not None:
        base = movement_entity_summary(context.movement)
        if auth_status:
            base['status'] = auth_status
            base['status_authority'] = 'action_log'
        elif meta_entity:
            base.update({k: v for k, v in meta_entity.items() if k not in base})
        return base

    return meta_entity


def authoritative_status_for_validation(context: ExecuteActionContext) -> str:
    """Log-primary status string for allowed-action validation."""
    job_detail_ctx = to_job_detail_context(context)
    return authoritative_entity_status(job_detail_ctx)
