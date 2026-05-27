"""
mobile_api/job_detail/services/job_detail_projection_service.py

Coordinate read-only projections for a resolved ``JobDetailContext``.
"""
from __future__ import annotations

from typing import Any

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.projections.job_header_projection import (
    build_job_header,
)
from mobile_api.job_detail.projections.pod_cod_projection import (
    build_pod_cod_section,
)
from mobile_api.job_detail.projections.round_trip_projection import (
    build_round_trip_section,
)
from mobile_api.job_detail.projections.sync_projection import (
    build_sync_metadata,
)
from mobile_api.job_detail.projections.timeline_projection import (
    build_timeline_section,
)
from mobile_api.job_detail.projections.workflow_projection import (
    build_workflow_section,
)
from mobile_api.job_detail.services.job_detail_projection_cache import (
    load_projection_cache,
)
from mobile_api.job_detail.services.job_detail_status_reconciler import (
    reconcile_job_detail_entities,
)


class JobDetailProjectionService:
    """
    Populate projection slices on ``JobDetailContext``.

    Order:
      1. Bounded Action Log prefetch
      2. Reconcile (log-primary, drift metadata)
      3. job_header
      4. workflow (reconciled overlays + Action Master)
      5. timeline / pod_cod / round_trip / alerts / sync_metadata
    """

    def apply_projections(
        self,
        context: JobDetailContext,
        *,
        request: Any | None = None,
    ) -> JobDetailContext:
        """Attach projection dicts after resolver success."""
        if not _resolver_ok(context):
            return context

        from mobile_api.job_detail.services.job_detail_projection_cache import (
            get_projection_cache,
        )

        if get_projection_cache(context) is None:
            load_projection_cache(context)
        if not context.reconciliation:
            reconcile_job_detail_entities(context, request=request)

        context.job_header = build_job_header(context, request=request)
        context.workflow = build_workflow_section(context, request=request)
        context.timeline = build_timeline_section(context, request=request)
        from mobile_api.job_detail.projections.job_detail_projection_builder import (
            apply_operational_issues_visibility,
        )

        apply_operational_issues_visibility(context, request=request)
        context.pod_cod = build_pod_cod_section(context, request=request)
        context.round_trip = build_round_trip_section(context, request=request)
        # Preserve any alerts already attached by projections/services (e.g.
        # operational issue escalation alerts and execution warning overlays).
        existing_alerts = dict(getattr(context, 'alerts', None) or {})
        placeholder = self._build_alerts_placeholder(context)
        existing_alerts.update(placeholder)
        context.alerts = existing_alerts
        # ``sync_metadata`` / ETag finalized in ``finalize_job_detail_sync`` (context service).
        if not context.sync_metadata:
            context.sync_metadata = build_sync_metadata(context, request=request)
        return context

    def apply_workflow_projection(
        self,
        context: JobDetailContext,
        *,
        request: Any | None = None,
    ) -> dict[str, Any]:
        """Workflow only — assumes reconcile + cache already loaded."""
        return build_workflow_section(context, request=request)

    def _build_alerts_placeholder(self, context: JobDetailContext) -> dict[str, Any]:
        """TODO: operational alerts from reconciliation + compliance drift."""
        recon = context.reconciliation or {}
        alerts: dict[str, Any] = {}
        if recon.get('any_drift'):
            alerts['has_drift'] = True
        operational = (context.resolver_meta or {}).get('operational_reconciliation')
        if isinstance(operational, dict):
            alerts['reconciliation_alerts'] = list(operational.get('reconciliation_alerts') or [])
        return alerts


def _resolver_ok(context: JobDetailContext) -> bool:
    meta = context.resolver_meta or {}
    if meta.get('ownership_validated') is True:
        return True
    if context.job_type == 'shipment' and context.shipment is not None:
        return True
    if context.job_type == 'movement' and context.movement is not None:
        return True
    return False
