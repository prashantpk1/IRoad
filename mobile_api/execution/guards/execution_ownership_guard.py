"""
mobile_api/execution/guards/execution_ownership_guard.py

Tenant isolation, driver session, and object-level ownership before execution.

Reuses ``mobile_api.job_detail`` resolvers (which already enforce ownership);
this guard adds defense-in-depth and maps failures to ``ExecuteActionError``.
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext, JobType
from mobile_api.execution.exceptions import (
    ExecuteActionError,
    execute_action_error_from_resolver,
)
from mobile_api.job_detail.guards.ownership import (
    assert_driver_active,
    booking_is_driver_accessible,
    driver_owns_booking,
    driver_owns_movement,
    driver_owns_shipment_leg,
    movement_is_empty_move_job,
    movement_is_driver_accessible,
    shipment_is_driver_accessible,
)
from mobile_api.job_detail.services.booking_job_resolver import BookingJobResolver
from mobile_api.job_detail.services.movement_job_resolver import MovementJobResolver
from mobile_api.job_detail.services.shipment_job_resolver import ShipmentJobResolver
from mobile_api.helpers.backload_booking_redirect import (
    pivot_context_to_backload_booking,
)


class ExecutionOwnershipGuard:
    """
    Resolve explicit job scope and validate driver may execute.

    Validates:
      - tenant_schema (JWT tenant isolation)
      - driver active session
      - shipment leg assignment OR movement driver assignment
      - empty-move-only for movement jobs
      - entity accessible (not cancelled)
    """

    def __init__(
        self,
        *,
        shipment_resolver: ShipmentJobResolver | None = None,
        movement_resolver: MovementJobResolver | None = None,
        booking_resolver: BookingJobResolver | None = None,
    ) -> None:
        self._shipment_resolver = shipment_resolver or ShipmentJobResolver()
        self._movement_resolver = movement_resolver or MovementJobResolver()
        self._booking_resolver = booking_resolver or BookingJobResolver()

    def assert_tenant_and_driver(self, context: ExecuteActionContext) -> None:
        """JWT tenant + driver principal (view layer should already authenticate)."""
        schema = (context.tenant_schema or '').strip()
        if not schema:
            raise ExecuteActionError(
                str(_('mobile.auth.tenant_required')),
                code='tenant_required',
                http_status=400,
                message_key='mobile.auth.tenant_required',
            )
        if context.driver is None:
            raise ExecuteActionError(
                str(_('mobile.auth.unauthorized')),
                code='driver_not_resolved',
                http_status=401,
                message_key='mobile.auth.unauthorized',
            )
        driver_err = assert_driver_active(context.driver)
        if driver_err:
            raise ExecuteActionError(
                str(_('mobile.auth.driver_inactive')),
                code=driver_err,
                http_status=401,
                message_key='mobile.auth.unauthorized',
            )

    def resolve_entity(self, context: ExecuteActionContext) -> None:
        """
        Resolve shipment or empty-move by ``job_type`` + ``job_id``.

        Populates ``shipment`` / ``movement`` / ``booking`` / ``resolver_meta``.
        Must run inside ``schema_context(context.tenant_schema)``.
        """
        self.assert_tenant_and_driver(context)
        job_id = (context.job_id or '').strip()
        if not job_id:
            raise ExecuteActionError(
                str(_('mobile.validation.failed')),
                code='invalid_job_reference',
                http_status=400,
                message_key='mobile.validation.failed',
            )

        if context.job_type == 'shipment':
            self._resolve_shipment(context, job_id)
            return
        if context.job_type == 'booking':
            self._resolve_booking(context, job_id)
            return
        self._resolve_movement(context, job_id)

    def assert_driver_may_execute(self, context: ExecuteActionContext) -> None:
        """
        Defense-in-depth ownership after resolve.

        Resolvers already validate; this re-checks assignment rules on ORM rows.
        """
        self.assert_tenant_and_driver(context)

        if context.job_type == 'shipment':
            shipment = context.shipment
            if shipment is None:
                raise ExecuteActionError(
                    str(_('mobile.jobs.not_found')),
                    code='job_not_found',
                    http_status=404,
                    message_key='mobile.jobs.not_found',
                )
            if not shipment_is_driver_accessible(shipment):
                raise ExecuteActionError(
                    str(_('mobile.jobs.inactive')),
                    code='job_inactive',
                    http_status=404,
                    message_key='mobile.jobs.inactive',
                )
            if not driver_owns_shipment_leg(
                context.driver,
                context.booking,
                shipment,
            ):
                raise ExecuteActionError(
                    str(_('mobile.auth.forbidden')),
                    code='forbidden',
                    http_status=403,
                    message_key='mobile.auth.forbidden',
                )
            return

        if context.job_type == 'booking':
            booking = context.booking
            if booking is None:
                raise ExecuteActionError(
                    str(_('mobile.jobs.not_found')),
                    code='job_not_found',
                    http_status=404,
                    message_key='mobile.jobs.not_found',
                )
            if not booking_is_driver_accessible(booking):
                raise ExecuteActionError(
                    str(_('mobile.jobs.inactive')),
                    code='job_inactive',
                    http_status=404,
                    message_key='mobile.jobs.inactive',
                )
            if not driver_owns_booking(context.driver, booking):
                raise ExecuteActionError(
                    str(_('mobile.auth.forbidden')),
                    code='forbidden',
                    http_status=403,
                    message_key='mobile.auth.forbidden',
                )
            return

        movement = context.movement
        if movement is None:
            raise ExecuteActionError(
                str(_('mobile.jobs.not_found')),
                code='job_not_found',
                http_status=404,
                message_key='mobile.jobs.not_found',
            )
        if not movement_is_empty_move_job(movement):
            raise ExecuteActionError(
                str(_('mobile.jobs.not_empty_move')),
                code='not_empty_move',
                http_status=400,
                message_key='mobile.jobs.not_empty_move',
            )
        if not movement_is_driver_accessible(movement):
            raise ExecuteActionError(
                str(_('mobile.jobs.inactive')),
                code='job_inactive',
                http_status=404,
                message_key='mobile.jobs.inactive',
            )
        if not driver_owns_movement(context.driver, movement):
            raise ExecuteActionError(
                str(_('mobile.auth.forbidden')),
                code='forbidden',
                http_status=403,
                message_key='mobile.auth.forbidden',
            )

    def _resolve_shipment(self, context: ExecuteActionContext, job_id: str) -> None:
        result = self._shipment_resolver.resolve(
            context.driver,
            job_id,
            tenant_schema=context.tenant_schema,
        )
        if result.resolve_context is not None and not result.resolve_context.ok:
            raise execute_action_error_from_resolver(
                error_code=result.error_code,
                error_message=result.error_message,
            )
        if result.shipment is None:
            raise execute_action_error_from_resolver(
                error_code=result.error_code or 'job_not_found',
                error_message=result.error_message,
            )
        context.shipment = result.shipment
        context.booking = result.booking
        if result.resolve_context is not None:
            context.resolver_meta = result.resolve_context.to_resolver_meta()
        if context.booking is not None and context.shipment is not None:
            pivot_context_to_backload_booking(
                driver=context.driver,
                booking=context.booking,
                shipment=context.shipment,
                context=context,
            )

    def _resolve_booking(self, context: ExecuteActionContext, job_id: str) -> None:
        result = self._booking_resolver.resolve(
            context.driver,
            job_id,
            tenant_schema=context.tenant_schema,
        )
        if result.resolve_context is not None and not result.resolve_context.ok:
            raise execute_action_error_from_resolver(
                error_code=result.error_code,
                error_message=result.error_message,
            )
        if result.booking is None:
            raise execute_action_error_from_resolver(
                error_code=result.error_code or 'job_not_found',
                error_message=result.error_message,
            )
        context.booking = result.booking
        if result.resolve_context is not None:
            context.resolver_meta = result.resolve_context.to_resolver_meta()

    def _resolve_movement(self, context: ExecuteActionContext, job_id: str) -> None:
        result = self._movement_resolver.resolve(
            context.driver,
            job_id,
            tenant_schema=context.tenant_schema,
        )
        if result.resolve_context is not None and not result.resolve_context.ok:
            raise execute_action_error_from_resolver(
                error_code=result.error_code,
                error_message=result.error_message,
            )
        if result.movement is None:
            raise execute_action_error_from_resolver(
                error_code=result.error_code or 'job_not_found',
                error_message=result.error_message,
            )
        context.movement = result.movement
        if result.resolve_context is not None:
            context.resolver_meta = result.resolve_context.to_resolver_meta()

    @staticmethod
    def normalize_job_type(job_type: str) -> JobType:
        token = (str(job_type) if job_type is not None else '').strip().casefold()
        if token in ('shipment', 'shipments'):
            return 'shipment'
        if token in ('movement', 'movements', 'empty_move', 'empty-move'):
            return 'movement'
        if token in ('booking', 'bookings'):
            return 'booking'
        raise ExecuteActionError(
            f'unsupported job_type: {job_type!r}',
            code='invalid_job_type',
            http_status=400,
            message_key='mobile.validation.failed',
        )
