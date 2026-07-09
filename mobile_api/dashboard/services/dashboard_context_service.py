"""
mobile_api/dashboard/services/dashboard_context_service.py

Main orchestration entry for the Unified Driver Dashboard.
"""
from __future__ import annotations

from typing import Any

from django_tenants.utils import schema_context

from mobile_api.dashboard.dto.dashboard_resolve_result import (
    DashboardResolveResult,
)
from mobile_api.dashboard.dto.dashboard_response_builder import (
    DashboardResponseBuilder,
)
from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.polling_constants import DASHBOARD_ETAG_ENABLED
from mobile_api.dashboard.projections.booking_projection import (
    build_booking_card_from_selection,
)
from mobile_api.dashboard.projections.pod_cod_projection import (
    build_pod_cod_summary_for_context,
)
from mobile_api.dashboard.projections.workflow_projection import (
    build_workflow_for_dashboard_context,
)
from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
from mobile_api.dashboard.selectors.dashboard_booking_selector import (
    DashboardBookingSelector,
)
from mobile_api.dashboard.selectors.dashboard_movement_selector import (
    DashboardMovementSelector,
)
from mobile_api.dashboard.services.booking_projection_service import (
    BookingProjectionService,
)
from mobile_api.dashboard.services.dashboard_cache_service import (
    apply_cached_projections_to_context,
    cached_etag,
    get_cached_projections,
    set_cached_projections,
)
from mobile_api.dashboard.services.dashboard_etag_service import (
    build_content_fingerprint,
    build_etag_from_fingerprint,
    build_invalidation_fingerprint,
    etag_matches_request,
    fingerprint_digest,
)
from mobile_api.dashboard.services.dashboard_projection_cache import (
    load_projection_cache,
)
from mobile_api.dashboard.services.dashboard_status_reconciler import (
    apply_reconciled_status_overlays,
    build_reconciliation_version,
    build_workflow_projection_version_token,
    reconcile_dashboard_entities,
)
from mobile_api.dashboard.services.dashboard_summary_service import (
    DashboardSummaryService,
)
from mobile_api.dashboard.services.driver_resolver import (
    assert_dashboard_scope_ownership,
)
from mobile_api.dashboard.services.movement_projection_service import (
    MovementProjectionService,
)


class DashboardContextService:
    """
    Resolves the full driver dashboard context for one authenticated driver.

    Polling optimizations:
      - One Action Log scan per request (``load_projection_cache``).
      - Reconcile + compliance before cache lookup (precise invalidation).
      - Projection cache + ETag / 304 when payload unchanged.
    """

    def __init__(
        self,
        *,
        booking_selector: DashboardBookingSelector | None = None,
        movement_selector: DashboardMovementSelector | None = None,
        booking_projection_service: BookingProjectionService | None = None,
        movement_projection_service: MovementProjectionService | None = None,
        summary_service: DashboardSummaryService | None = None,
        response_builder: DashboardResponseBuilder | None = None,
    ) -> None:
        self._booking_selector = booking_selector or DashboardBookingSelector()
        self._movement_selector = movement_selector or DashboardMovementSelector()
        self._booking_projection = (
            booking_projection_service or BookingProjectionService()
        )
        self._movement_projection = (
            movement_projection_service or MovementProjectionService()
        )
        self._summary_service = summary_service or DashboardSummaryService()
        self._response_builder = response_builder or DashboardResponseBuilder()

    def resolve_driver_dashboard(
        self,
        driver: Any,
        *,
        tenant_schema: str,
        user_id: str,
        jwt_payload: dict | None = None,
        request: Any | None = None,
    ) -> DashboardResolveResult:
        schema = (tenant_schema or '').strip()
        if not schema:
            raise ValueError('tenant_schema required for dashboard resolution')

        with schema_context(schema):
            context = self.resolve_driver_dashboard_context(
                driver,
                tenant_schema=schema,
                user_id=user_id,
                jwt_payload=jwt_payload,
                request=request,
            )
        if context.poll_not_modified:
            return DashboardResolveResult(
                context=context,
                etag=context.dashboard_etag,
                not_modified=True,
            )
        return DashboardResolveResult(
            context=context,
            etag=context.dashboard_etag,
            not_modified=False,
        )

    def resolve_driver_dashboard_context(
        self,
        driver: Any,
        *,
        tenant_schema: str,
        user_id: str,
        jwt_payload: dict | None = None,
        request: Any | None = None,
    ) -> DriverDashboardContext:
        _ = jwt_payload
        context = DriverDashboardContext(
            driver=driver,
            tenant_schema=tenant_schema,
            user_id=user_id,
        )
        driver_pk = booking_policy._driver_pk(driver)

        booking_selection = self._booking_selector.select_current_driver_booking(
            driver,
            tenant_schema=tenant_schema,
        )
        if booking_selection is not None:
            context.booking_selection = booking_selection
            context.active_booking = booking_selection.booking
            context.active_shipment = booking_selection.active_shipment

        exclude_booking_id = None
        if context.active_booking is not None:
            exclude_booking_id = (
                getattr(context.active_booking, 'booking_id', None)
                or context.active_booking.pk
            )

        empty_selection = self._movement_selector.select_current_empty_move(
            driver,
            tenant_schema=tenant_schema,
            exclude_booking_id=exclude_booking_id,
        )
        if empty_selection is not None:
            from mobile_api.dashboard.selectors.movement_selection_policy import (
                is_active_empty_move,
            )

            if is_active_empty_move(empty_selection.movement):
                context.empty_move_selection = empty_selection
                context.active_empty_movement = empty_selection.movement

        assert_dashboard_scope_ownership(
            driver,
            active_booking=context.active_booking,
            active_shipment=context.active_shipment,
            active_movement=context.active_empty_movement,
        )

        projection_cache = load_projection_cache(context)
        reconcile_dashboard_entities(
            context,
            request=request,
            projection_cache=projection_cache,
        )

        recon = context.reconciliation or {}
        pod_flags = dict(recon.get('pod_cod_flags') or {})

        inv_fp = build_invalidation_fingerprint(
            context,
            latest_action_log_id=context.latest_action_log_id,
            pod_cod=pod_flags,
        )

        if driver_pk is not None:
            cached = get_cached_projections(
                tenant_schema,
                driver_pk,
                inv_fp,
            )
            if cached is not None:
                etag = cached_etag(cached)
                if (
                    DASHBOARD_ETAG_ENABLED
                    and request is not None
                    and etag_matches_request(request, etag)
                ):
                    context.dashboard_etag = etag
                    context.content_hash = fingerprint_digest(
                        build_content_fingerprint(
                            context,
                            latest_action_log_id=context.latest_action_log_id,
                            pod_cod=pod_flags,
                        )
                    )
                    context.poll_not_modified = True
                    return context

                apply_cached_projections_to_context(context, cached)
                self._attach_workflow_version_token(context)
                content_fp = build_content_fingerprint(
                    context,
                    latest_action_log_id=context.latest_action_log_id,
                    pod_cod=context.pod_cod_projection,
                )
                context.dashboard_etag = etag or build_etag_from_fingerprint(content_fp)
                context.content_hash = fingerprint_digest(content_fp)
                self._finalize_summary(context, request=request)
                return context

        self._build_projections_full(context, tenant_schema=tenant_schema, request=request)

        content_fp = build_content_fingerprint(
            context,
            latest_action_log_id=context.latest_action_log_id,
            pod_cod=context.pod_cod_projection,
        )
        context.content_hash = fingerprint_digest(content_fp)
        if driver_pk is not None:
            context.dashboard_etag = set_cached_projections(
                tenant_schema,
                driver_pk,
                inv_fp,
                context=context,
                content_fingerprint=content_fp,
            )
        else:
            context.dashboard_etag = build_etag_from_fingerprint(content_fp)

        self._finalize_summary(context, request=request)
        return context

    def _attach_workflow_version_token(self, context: DriverDashboardContext) -> None:
        if not context.reconciliation:
            return
        context.reconciliation['workflow_projection_version'] = (
            build_workflow_projection_version_token(context.workflow_projection)
        )

    def _build_projections_full(
        self,
        context: DriverDashboardContext,
        *,
        tenant_schema: str,
        request: Any | None,
    ) -> None:
        with apply_reconciled_status_overlays(context):
            if context.empty_move_selection is not None and context.active_empty_movement is not None:
                from mobile_api.dashboard.selectors.dashboard_movement_selector import (
                    DashboardMovementSelector,
                )

                context.empty_move_selection = DashboardMovementSelector._result_from_movement(
                    context.active_empty_movement,
                )
            if context.booking_selection is not None:
                context.booking_projection = build_booking_card_from_selection(
                    context.booking_selection,
                    tenant_schema=tenant_schema,
                    request=request,
                )
            if context.empty_move_selection is not None:
                context.movement_projection = self._movement_projection.project_empty_move(
                    selection=context.empty_move_selection,
                    request=request,
                )
            context.workflow_projection = build_workflow_for_dashboard_context(
                context,
                request=request,
            )
            context.pod_cod_projection = build_pod_cod_summary_for_context(context)

        self._attach_workflow_version_token(context)
        if context.reconciliation:
            context.reconciliation['reconciliation_version'] = (
                build_reconciliation_version(context.reconciliation)
            )

    def _finalize_summary(
        self,
        context: DriverDashboardContext,
        *,
        request: Any | None,
    ) -> None:
        context.summary = self._summary_service.build_summary(context, request=request)
        context.sync_metadata = self._summary_service.build_sync_metadata(context)

    def build_api_payload(
        self,
        context: DriverDashboardContext,
        *,
        request: Any | None = None,
    ) -> dict:
        _ = request
        return dict(self._response_builder.build(context, request=request))
