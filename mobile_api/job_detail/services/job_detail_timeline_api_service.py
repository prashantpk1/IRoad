"""
mobile_api/job_detail/services/job_detail_timeline_api_service.py

Timeline-only orchestration for GET .../jobs/<job_type>/<job_id>/timeline/

Does **not** run workflow, POD/COD, reconcile, or full Job Detail projections.
"""
from __future__ import annotations

from typing import Any

from django_tenants.utils import schema_context

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext, JobType
from mobile_api.job_detail.exceptions import (
    JobDetailError,
    job_detail_error_from_resolver,
)
from mobile_api.job_detail.services.job_detail_context_service import (
    JobDetailContextService,
)
from mobile_api.job_detail.services.movement_job_resolver import (
    MovementJobResolver,
)
from mobile_api.job_detail.services.shipment_job_resolver import (
    ShipmentJobResolver,
)
from mobile_api.job_detail.timeline.timeline_cursor_service import (
    JobDetailTimelineCursorService,
)
from mobile_api.job_detail.timeline.timeline_service import JobDetailTimelineService


class JobDetailTimelineApiService:
    """
    Resolve explicit job scope and return one paginated Action Log page.

    Single bounded ``timeline_query`` read per request — no workflow engine.
    """

    def __init__(
        self,
        *,
        context_service: JobDetailContextService | None = None,
        shipment_resolver: ShipmentJobResolver | None = None,
        movement_resolver: MovementJobResolver | None = None,
        timeline_service: JobDetailTimelineService | None = None,
        cursor_service: JobDetailTimelineCursorService | None = None,
    ) -> None:
        self._context_service = context_service or JobDetailContextService()
        self._shipment_resolver = shipment_resolver or ShipmentJobResolver()
        self._movement_resolver = movement_resolver or MovementJobResolver()
        self._timeline_service = timeline_service or JobDetailTimelineService()
        self._cursor_service = cursor_service or JobDetailTimelineCursorService()

    def fetch_timeline_page(
        self,
        driver: Any,
        job_type: JobType | str,
        job_id: str,
        *,
        tenant_schema: str,
        user_id: str = '',
        cursor: str | None = None,
        limit: int | None = None,
        request: Any | None = None,
    ) -> dict[str, Any]:
        """
        Return API contract: ``events``, ``next_cursor``, ``has_more``.

        Raises:
            JobDetailError: resolver / tenant / cursor failures.
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

        token = (cursor or '').strip()
        if token and not self._cursor_service.validate_cursor_token(token):
            raise JobDetailError(
                'Invalid timeline cursor',
                code='invalid_timeline_cursor',
                http_status=400,
                message_key='mobile.validation.failed',
            )

        normalized_type = self._context_service._normalize_job_type(job_type)
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
            return self._timeline_service.fetch_timeline_api_page(
                context,
                cursor=token or None,
                limit=limit,
                request=request,
            )

    def _resolve_entity(self, context: JobDetailContext) -> None:
        """Shipment or movement resolver only — no projection cache."""
        if context.job_type == 'shipment':
            result = self._shipment_resolver.resolve(
                context.driver,
                context.job_id,
                tenant_schema=context.tenant_schema,
            )
            if result.resolve_context is not None and not result.resolve_context.ok:
                raise job_detail_error_from_resolver(
                    error_code=result.error_code,
                    error_message=result.error_message,
                )
            if result.shipment is None:
                raise job_detail_error_from_resolver(
                    error_code=result.error_code or 'job_not_found',
                    error_message=result.error_message,
                )
            context.shipment = result.shipment
            context.booking = result.booking
            return

        result = self._movement_resolver.resolve(
            context.driver,
            context.job_id,
            tenant_schema=context.tenant_schema,
        )
        if result.resolve_context is not None and not result.resolve_context.ok:
            raise job_detail_error_from_resolver(
                error_code=result.error_code,
                error_message=result.error_message,
            )
        if result.movement is None:
            raise job_detail_error_from_resolver(
                error_code=result.error_code or 'job_not_found',
                error_message=result.error_message,
            )
        context.movement = result.movement
