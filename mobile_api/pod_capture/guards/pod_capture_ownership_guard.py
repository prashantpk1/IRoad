"""
mobile_api/pod_capture/guards/pod_capture_ownership_guard.py

Tenant isolation, driver session, and shipment-only ownership for POD capture.

Validates before staging:

1. Shipment exists (resolver)
2. Shipment belongs to driver (leg assignment)
3. Shipment belongs to tenant (schema_context + resolver)
4. Shipment active (not cancelled)
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from mobile_api.job_detail.guards.ownership import (
    assert_driver_active,
    driver_owns_shipment_leg,
    shipment_is_driver_accessible,
)
from mobile_api.job_detail.services.shipment_job_resolver import resolve_shipment_job
from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.staging_models import PODCaptureBundle, StagingScope
from mobile_api.pod_capture.exceptions import (
    PodCaptureError,
    pod_capture_error_from_resolver,
)
from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService


class PodCaptureOwnershipGuard:
    """
    Resolve explicit shipment scope and validate driver may stage POD evidence.

    Does **not** check Action Master allowed-actions — capture is evidence-only;
    workflow eligibility is enforced on Execute Action.
    """

    def __init__(self, *, staging: EvidenceStagingService | None = None) -> None:
        self._staging = staging or EvidenceStagingService()

    def assert_tenant_and_driver(self, context: PodCaptureContext) -> None:
        schema = (context.tenant_schema or '').strip()
        if not schema:
            raise PodCaptureError(
                str(_('mobile.auth.tenant_required')),
                code='tenant_required',
                http_status=400,
                message_key='mobile.auth.tenant_required',
            )
        if context.driver is None:
            raise PodCaptureError(
                str(_('mobile.auth.unauthorized')),
                code='driver_not_resolved',
                http_status=401,
                message_key='mobile.auth.unauthorized',
            )
        driver_err = assert_driver_active(context.driver)
        if driver_err:
            raise PodCaptureError(
                str(_('mobile.auth.driver_inactive')),
                code=driver_err,
                http_status=401,
                message_key='mobile.auth.unauthorized',
            )

    def assert_shipment_only(self, *, job_type: str) -> None:
        token = (job_type or '').strip().casefold()
        if token and token != 'shipment':
            raise PodCaptureError(
                str(_('mobile.pod_capture.shipment_only')),
                code='pod_capture_shipment_only',
                http_status=400,
                message_key='mobile.pod_capture.shipment_only',
            )

    def resolve_shipment(self, context: PodCaptureContext) -> None:
        """
        Populate ``context.shipment`` with ownership checks.

        Caller must already run inside ``schema_context(tenant_schema)`` so the
        shipment row belongs to the JWT tenant database.
        """
        self.assert_tenant_and_driver(context)

        resolved = resolve_shipment_job(
            context.driver,
            context.shipment_id,
            tenant_schema=context.tenant_schema,
        )
        if not resolved.ownership_validated or resolved.shipment is None:
            raise pod_capture_error_from_resolver(
                error_code=resolved.error_code,
                error_message=resolved.error_message,
            )

        shipment = resolved.shipment
        self.assert_shipment_active(shipment)
        self.assert_shipment_driver_assignment(
            context,
            shipment=shipment,
            booking=resolved.booking,
        )

        context.shipment = shipment
        context.booking = resolved.booking
        context.shipment_id = str(
            getattr(shipment, 'pk', None)
            or getattr(shipment, 'shipment_id', None)
            or context.shipment_id
        )
        context.resolver_meta = dict(context.resolver_meta or {})
        context.resolver_meta['shipment_no'] = str(
            getattr(shipment, 'shipment_no', '') or ''
        )

    def validate_capture_scope(self, context: PodCaptureContext) -> StagingScope:
        """
        Full pre-staging ownership validation (rules 1–4).

        Returns canonical :class:`StagingScope` for media linkage.
        """
        if context.shipment is None:
            raise PodCaptureError(
                str(_('mobile.jobs.not_found')),
                code='job_not_found',
                http_status=404,
                message_key='mobile.jobs.not_found',
            )

        scope = self._staging.scope_from_context(context)
        if not scope.tenant_schema or not scope.driver_id or not scope.shipment_id:
            raise PodCaptureError(
                str(_('mobile.pod_capture.scope_incomplete')),
                code='scope_incomplete',
                http_status=400,
                message_key='mobile.pod_capture.scope_incomplete',
            )
        return scope

    def assert_bundle_allowed_for_capture(
        self,
        context: PodCaptureContext,
        bundle: PODCaptureBundle,
    ) -> None:
        """Idempotent replay — re-check bundle not promoted/expired and scope matches."""
        scope = self._staging.scope_from_context(context)
        self._staging.assert_bundle_scope(bundle, scope)
        self._staging.assert_bundle_mutable_for_capture(bundle)

    @staticmethod
    def assert_shipment_active(shipment: Any) -> None:
        if not shipment_is_driver_accessible(shipment):
            raise PodCaptureError(
                str(_('mobile.jobs.inactive')),
                code='job_inactive',
                http_status=404,
                message_key='mobile.jobs.inactive',
            )

    @staticmethod
    def assert_shipment_driver_assignment(
        context: PodCaptureContext,
        *,
        shipment: Any,
        booking: Any | None,
    ) -> None:
        if not driver_owns_shipment_leg(context.driver, booking, shipment):
            raise PodCaptureError(
                str(_('mobile.auth.forbidden')),
                code='forbidden',
                http_status=403,
                message_key='mobile.auth.forbidden',
            )

    @staticmethod
    def driver_pk(driver: Any) -> str:
        if driver is None:
            return ''
        pk = getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)
        return str(pk or '').strip()
