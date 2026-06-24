"""
mobile_api/job_detail/services/job_detail_context_service.py

Main orchestrator for the Unified Job Detail API.

Explicit job scope only — does **not** select the driver's current job.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from django_tenants.utils import schema_context

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext, JobType
from mobile_api.job_detail.dto.job_detail_response_builder import (
    JobDetailApiPayload,
    JobDetailResponseBuilder,
)
from mobile_api.job_detail.exceptions import (
    JobDetailError,
    job_detail_error_from_resolver,
)
from mobile_api.job_detail.services.job_detail_projection_cache import (
    load_projection_cache,
)
from mobile_api.job_detail.services.job_detail_projection_service import (
    JobDetailProjectionService,
)
from mobile_api.job_detail.services.job_detail_status_reconciler import (
    reconcile_job_detail_entities,
)
from mobile_api.job_detail.services.job_detail_sync_metadata import (
    finalize_job_detail_sync,
    should_short_circuit_polling,
)
from mobile_api.job_detail.helpers.resolve_job_entity import resolve_job_detail_entity
from mobile_api.job_detail.services.booking_job_resolver import BookingJobResolver
from mobile_api.job_detail.services.movement_job_resolver import MovementJobResolver
from mobile_api.job_detail.services.shipment_job_resolver import ShipmentJobResolver


@dataclass
class JobDetailResolveResult:
    """Service result including optional 304 polling state."""

    context: JobDetailContext
    etag: str = ''
    not_modified: bool = False


class JobDetailContextService:
    """
    Resolve full Job Detail orchestration context for one job.

    High-level pipeline::

        schema_context(tenant_schema)
          → resolve entity by job_type + job_id (resolver + ownership)
          → single bounded Action Log prefetch
          → reconcile workflow + compliance
          → projections (workflow, timeline, pod_cod, round_trip, sync)
          → content_hash / ETag / optional 304
    """

    def __init__(
        self,
        *,
        shipment_resolver: ShipmentJobResolver | None = None,
        movement_resolver: MovementJobResolver | None = None,
        booking_resolver: BookingJobResolver | None = None,
        projection_service: JobDetailProjectionService | None = None,
        response_builder: JobDetailResponseBuilder | None = None,
    ) -> None:
        self._shipment_resolver = shipment_resolver or ShipmentJobResolver()
        self._movement_resolver = movement_resolver or MovementJobResolver()
        self._booking_resolver = booking_resolver or BookingJobResolver()
        self._projection_service = projection_service or JobDetailProjectionService()
        self._response_builder = response_builder or JobDetailResponseBuilder()

    def resolve_job_detail_context(
        self,
        driver: Any,
        job_type: JobType | str,
        job_id: str,
        *,
        tenant_schema: str,
        user_id: str = '',
        request: Any | None = None,
    ) -> JobDetailContext:
        """
        Build in-memory ``JobDetailContext`` for one explicit job.

        Raises:
            JobDetailError: resolver / tenant / reference failures.
            ValueError: unsupported ``job_type``.
        """
        schema = (tenant_schema or '').strip()
        if not schema:
            raise JobDetailError(
                'tenant_schema required',
                code='tenant_required',
                http_status=400,
                message_key='mobile.auth.tenant_required',
            )

        normalized_type = self._normalize_job_type(job_type)
        normalized_id = (job_id or '').strip()
        if not normalized_id:
            raise JobDetailError(
                'job_id required',
                code='invalid_job_reference',
                http_status=400,
                message_key='mobile.validation.failed',
            )

        with schema_context(schema):
            context = JobDetailContext(
                driver=driver,
                tenant_schema=schema,
                user_id=(user_id or '').strip(),
                job_type=normalized_type,
                job_id=normalized_id,
            )
            self._resolve_entity(context)

            load_projection_cache(context)
            reconcile_job_detail_entities(context, request=request)

            if should_short_circuit_polling(context, request=request):
                return context

            self._projection_service.apply_projections(context, request=request)
            finalize_job_detail_sync(context, request=request)
        return context

    def resolve_job_detail(
        self,
        driver: Any,
        job_type: JobType | str,
        job_id: str,
        *,
        tenant_schema: str,
        user_id: str = '',
        jwt_payload: dict | None = None,
        request: Any | None = None,
    ) -> JobDetailResolveResult:
        """Resolve context and wrap polling metadata (ETag / 304)."""
        _ = jwt_payload
        context = self.resolve_job_detail_context(
            driver,
            job_type,
            job_id,
            tenant_schema=tenant_schema,
            user_id=user_id,
            request=request,
        )
        return JobDetailResolveResult(
            context=context,
            etag=context.job_etag,
            not_modified=context.poll_not_modified,
        )

    def build_api_payload(
        self,
        context: JobDetailContext,
        *,
        request: Any | None = None,
    ) -> JobDetailApiPayload:
        """Map orchestration context to outward API contract."""
        _ = request
        schema = (getattr(context, 'tenant_schema', None) or '').strip()
        if schema:
            with schema_context(schema):
                return self._response_builder.build(context)
        return self._response_builder.build(context)

    def _normalize_job_type(self, job_type: JobType | str) -> JobType:
        token = (str(job_type) if job_type is not None else '').strip().casefold()
        if token in ('shipment', 'shipments'):
            return 'shipment'
        if token in ('movement', 'movements', 'empty_move', 'empty-move'):
            return 'movement'
        if token in ('booking', 'bookings'):
            return 'booking'
        raise ValueError(f'unsupported job_type: {job_type!r}')

    def _resolve_entity(self, context: JobDetailContext) -> None:
        """Dispatch to booking/shipment/movement resolver; pivot backload when needed."""
        resolve_job_detail_entity(
            context,
            shipment_resolver=self._shipment_resolver,
            movement_resolver=self._movement_resolver,
            booking_resolver=self._booking_resolver,
        )
