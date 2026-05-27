"""
mobile_api/execution/services/execution_projection_cache.py

Per-request projection cache — single Action Log scan + section memoization.
"""
from __future__ import annotations

from typing import Any

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.services.execution_context_adapter import (
    sync_from_job_detail,
    to_job_detail_context,
)
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.projections.pod_cod_projection import build_pod_cod_section
from mobile_api.job_detail.projections.round_trip_projection import build_round_trip_section
from mobile_api.job_detail.projections.timeline_projection import build_timeline_section
from mobile_api.job_detail.projections.workflow_projection import build_workflow_section
from mobile_api.job_detail.services.job_detail_projection_cache import (
    JobDetailProjectionCache,
    load_projection_cache,
)
from mobile_api.job_detail.services.job_detail_projection_service import (
    JobDetailProjectionService,
)
from mobile_api.job_detail.services.job_detail_pod_cod_reconciler import (
    reconcile_job_detail_pod_cod,
)
from mobile_api.job_detail.services.job_detail_status_reconciler import (
    reconcile_job_detail_entities,
)
from mobile_api.job_detail.services.job_detail_sync_metadata import (
    build_job_detail_sync_metadata,
    resolve_content_hash,
)
from mobile_api.services.operational_reconciliation_service import (
    OperationalReconciliationService,
)


class ExecutionProjectionCache:
    """
    Memoize reconcile + read-model sections for one execute request.

    Pre-execute: load cache + reconcile + workflow + sync once.
    Post-execute: invalidate log head, reload cache once, rebuild all sections once.
    """

    def __init__(self, execute_context: ExecuteActionContext) -> None:
        self._execute_context = execute_context
        self._job_detail_ctx: JobDetailContext | None = None
        self._reconciled = False
        self._workflow_built = False
        self._timeline_built = False
        self._pod_cod_built = False
        self._alerts_built = False
        self._sync_built = False

    @property
    def job_detail_context(self) -> JobDetailContext:
        if self._job_detail_ctx is None:
            self._job_detail_ctx = to_job_detail_context(self._execute_context)
            if self._execute_context.projection_cache is not None:
                self._job_detail_ctx.projection_cache = self._execute_context.projection_cache
        return self._job_detail_ctx

    @classmethod
    def attach(cls, execute_context: ExecuteActionContext) -> ExecutionProjectionCache:
        existing = getattr(execute_context, '_execution_projection_cache', None)
        if isinstance(existing, ExecutionProjectionCache):
            return existing
        cache = cls(execute_context)
        execute_context._execution_projection_cache = cache  # type: ignore[attr-defined]
        return cache

    def ensure_log_cache(self, *, request: Any | None = None) -> JobDetailProjectionCache:
        ctx = self.job_detail_context
        cache = load_projection_cache(ctx)
        self._execute_context.projection_cache = cache
        return cache

    def ensure_pre_execute_reconcile(self, *, request: Any | None = None) -> dict[str, Any]:
        if self._reconciled:
            return dict(self._execute_context.reconciliation or {})
        ctx = self.job_detail_context
        self.ensure_log_cache(request=request)
        reconcile_job_detail_entities(ctx, request=request)
        if self._execute_context.job_type == 'shipment' and self._execute_context.shipment is not None:
            pod_bundle = reconcile_job_detail_pod_cod(ctx)
            ctx.pod_cod = dict(pod_bundle.get('flags') or {})
        self._reconciled = True
        sync_from_job_detail(self._execute_context, ctx)
        return dict(self._execute_context.reconciliation or {})

    def ensure_workflow(self, *, request: Any | None = None) -> dict[str, Any]:
        if not self._workflow_built:
            ctx = self.job_detail_context
            self.ensure_pre_execute_reconcile(request=request)
            workflow = build_workflow_section(ctx, request=request)
            ctx.workflow = workflow
            self._execute_context.workflow = dict(workflow)
            self._workflow_built = True
        return dict(self._execute_context.workflow or {})

    def ensure_sync_metadata(self, *, request: Any | None = None) -> dict[str, Any]:
        if not self._sync_built:
            ctx = self.job_detail_context
            self.ensure_pre_execute_reconcile(request=request)
            if not self._workflow_built:
                self.ensure_workflow(request=request)
            ctx.sync_metadata = build_job_detail_sync_metadata(ctx)
            ctx.content_hash = resolve_content_hash(ctx)
            sync_from_job_detail(self._execute_context, ctx)
            self._sync_built = True
        return dict(self._execute_context.sync_metadata or {})

    def invalidate_after_mutation(self) -> None:
        """Force one fresh log scan after Action Log append."""
        self._reconciled = False
        self._workflow_built = False
        self._timeline_built = False
        self._pod_cod_built = False
        self._alerts_built = False
        self._sync_built = False
        ctx = self.job_detail_context
        ctx.projection_cache = None
        self._execute_context.projection_cache = None
        if self._execute_context.action_log is not None:
            log_id = getattr(self._execute_context.action_log, 'log_id', None) or getattr(
                self._execute_context.action_log,
                'pk',
                None,
            )
            if log_id:
                ctx.latest_action_log_id = str(log_id)
                self._execute_context.latest_action_log_id = str(log_id)

    def build_post_execute_sections(self, *, request: Any | None = None) -> None:
        """Rebuild mobile-usable read model once after kernel / replay."""
        self.invalidate_after_mutation()
        ctx = self.job_detail_context
        self.ensure_log_cache(request=request)
        reconcile_job_detail_entities(ctx, request=request)

        if self._execute_context.job_type == 'shipment' and self._execute_context.shipment is not None:
            self._execute_context.pod_cod = build_pod_cod_section(ctx, request=request)
            self._execute_context.round_trip = build_round_trip_section(ctx, request=request)
            ctx.pod_cod = dict(self._execute_context.pod_cod or {})
            ctx.round_trip = dict(self._execute_context.round_trip or {})
        else:
            self._execute_context.pod_cod = {}
            self._execute_context.round_trip = {}
            ctx.pod_cod = {}
            ctx.round_trip = {}

        self._execute_context.workflow = build_workflow_section(ctx, request=request)
        ctx.workflow = dict(self._execute_context.workflow or {})

        self._execute_context.timeline = build_timeline_section(ctx, request=request)
        ctx.timeline = dict(self._execute_context.timeline or {})

        projection_svc = JobDetailProjectionService()
        ctx.resolver_meta = dict(ctx.resolver_meta or {})
        ctx.resolver_meta['operational_reconciliation'] = OperationalReconciliationService().reconcile(
            context=ctx,
            request=request,
        )
        placeholder = projection_svc._build_alerts_placeholder(ctx)
        merged_alerts = dict(self._execute_context.alerts or {})
        merged_alerts.update(placeholder)
        self._execute_context.alerts = merged_alerts
        ctx.alerts = dict(merged_alerts)

        ctx.sync_metadata = build_job_detail_sync_metadata(ctx)
        ctx.content_hash = resolve_content_hash(ctx)
        sync_from_job_detail(self._execute_context, ctx)

        self._reconciled = True
        self._workflow_built = True
        self._timeline_built = True
        self._pod_cod_built = True
        self._alerts_built = True
        self._sync_built = True
