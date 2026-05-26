"""
mobile_api/execution/services/execute_action_orchestrator.py

Main orchestrator for the Unified Execute Action API (shipment + empty move).

Delegates all mutations to ``iroad_tenants.services.ActionExecutionService``;
this module owns mobile boundary concerns only (resolve, reconcile overlay,
evidence, stale sync, response projection).
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django_tenants.utils import schema_context

from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
from iroad_tenants.services.action_execution_service import ActionExecutionService
from mobile_api.execution.dto.execute_action_context import ExecuteActionContext, JobType
from mobile_api.execution.dto.execute_action_result import ExecuteActionResult
from mobile_api.execution.dto.execution_authoritative_context import kernel_validation_overlay
from mobile_api.execution.dto.execution_validation_error import build_validation_error
from mobile_api.execution.evidence.evidence_validation_service import (
    EvidenceValidationService,
)
from mobile_api.execution.evidence.execution_media_service import ExecutionMediaService
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.guards.execution_idempotency_guard import (
    ExecutionIdempotencyGuard,
)
from mobile_api.execution.guards.execution_locking import lock_execution_entities
from mobile_api.execution.guards.execution_ownership_guard import ExecutionOwnershipGuard
from mobile_api.execution.guards.stale_execution_guard import StaleExecutionGuard
from mobile_api.execution.services.execution_reconcile_service import (
    ExecutionReconcileService,
)
from mobile_api.execution.services.execution_response_service import (
    ExecutionResponseService,
)
from mobile_api.execution.services.execution_validation_service import (
    ExecutionValidationService,
)
from mobile_api.helpers.mobile_execution_guard import (
    MobileExecutionContext,
    mobile_execution_guard,
)
from mobile_api.job_detail.services.movement_job_resolver import MovementJobResolver
from mobile_api.job_detail.services.shipment_job_resolver import ShipmentJobResolver

logger = logging.getLogger('mobile_api.execution')


class ExecuteActionOrchestrator:
    """
    Unified mobile execute-action front door.

    Pipeline (single outer ``transaction.atomic``)::

        schema_context(tenant_schema)
          → prepare_pre_execute (resolve, ownership, reconcile, workflow overlay)
          → normalize idempotency + replay short-circuit (before validation/kernel)
          → validate_pre_execute (stale, allowed-action) when not replay
          → validate_required_evidence + media security
          → row locks + mobile_execution_guard + kernel (reconciled overlay)
          → persist_execution_media
          → reconcile_post_execute + build response
    """

    def __init__(
        self,
        *,
        shipment_resolver: ShipmentJobResolver | None = None,
        movement_resolver: MovementJobResolver | None = None,
        ownership_guard: ExecutionOwnershipGuard | None = None,
        reconcile_service: ExecutionReconcileService | None = None,
        validation_service: ExecutionValidationService | None = None,
        evidence_service: EvidenceValidationService | None = None,
        media_service: ExecutionMediaService | None = None,
        idempotency_guard: ExecutionIdempotencyGuard | None = None,
        stale_guard: StaleExecutionGuard | None = None,
        response_service: ExecutionResponseService | None = None,
    ) -> None:
        self._shipment_resolver = shipment_resolver or ShipmentJobResolver()
        self._movement_resolver = movement_resolver or MovementJobResolver()
        self._ownership_guard = ownership_guard or ExecutionOwnershipGuard(
            shipment_resolver=self._shipment_resolver,
            movement_resolver=self._movement_resolver,
        )
        self._reconcile_service = reconcile_service or ExecutionReconcileService(
            ownership_guard=self._ownership_guard,
        )
        self._validation_service = validation_service or ExecutionValidationService(
            reconcile_service=self._reconcile_service,
        )
        self._evidence_service = evidence_service or EvidenceValidationService()
        self._media_service = media_service or ExecutionMediaService()
        self._idempotency_guard = idempotency_guard or ExecutionIdempotencyGuard()
        self._stale_guard = stale_guard or StaleExecutionGuard()
        self._response_service = response_service or ExecutionResponseService(
            reconcile_service=self._reconcile_service,
        )

    def execute_driver_action(
        self,
        *,
        driver: Any,
        tenant: Any,
        job_type: str,
        job_id: str,
        action_code: str,
        payload: Mapping[str, Any],
        request: Any | None = None,
        tenant_user: Any | None = None,
        user_id: str = '',
    ) -> ExecuteActionResult:
        """
        Execute one driver workflow action for an explicit job.

        All mobile writes go through ``ActionExecutionService.execute_driver_action``
        inside ``mobile_execution_guard`` with ``SOURCE_CHANNEL_MOBILE_DRIVER``.
        """
        tenant_schema = getattr(tenant, 'schema_name', None) or str(tenant)
        normalized_job_type = self._normalize_job_type(job_type)
        normalized_action = (action_code or '').strip()
        if not normalized_action:
            raise ExecuteActionError(
                'action_code is required.',
                code='action_code_required',
                http_status=400,
                message_key='mobile.jobs.execute.action_code_required',
            )

        with schema_context(tenant_schema):
            return self._execute_driver_action_atomic(
                driver=driver,
                tenant_schema=tenant_schema,
                job_type=normalized_job_type,
                job_id=str(job_id).strip(),
                action_code=normalized_action,
                payload=dict(payload),
                request=request,
                tenant_user=tenant_user,
                user_id=(user_id or str(getattr(driver, 'user_id', '') or '')).strip(),
            )

    @transaction.atomic
    def _execute_driver_action_atomic(
        self,
        *,
        driver: Any,
        tenant_schema: str,
        job_type: JobType,
        job_id: str,
        action_code: str,
        payload: dict[str, Any],
        request: Any | None,
        tenant_user: Any | None,
        user_id: str,
    ) -> ExecuteActionResult:
        """Inner pipeline — ``transaction.atomic`` boundary for production."""
        return self._run_execute_pipeline(
            driver=driver,
            tenant_schema=tenant_schema,
            job_type=job_type,
            job_id=job_id,
            action_code=action_code,
            payload=payload,
            request=request,
            tenant_user=tenant_user,
            user_id=user_id,
        )

    def _run_execute_pipeline(
        self,
        *,
        driver: Any,
        tenant_schema: str,
        job_type: JobType,
        job_id: str,
        action_code: str,
        payload: dict[str, Any],
        request: Any | None,
        tenant_user: Any | None,
        user_id: str,
    ) -> ExecuteActionResult:
        """Execute pipeline body (testable without opening a DB transaction)."""
        context = ExecuteActionContext(
            driver=driver,
            tenant_schema=tenant_schema,
            user_id=user_id,
            job_type=job_type,
            job_id=job_id,
            action_code=action_code,
            payload=payload,
        )

        # 1–4. resolve, ownership, reconcile, workflow + sync (single projection pass)
        self._reconcile_service.prepare_pre_execute(context, request=request)

        # 5. idempotency normalize + replay detect BEFORE stale / kernel validation
        keys = self._idempotency_guard.normalize_request_keys(context)
        is_replay = self._idempotency_guard.detect_idempotent_replay(context, keys)

        if is_replay:
            context.reused_existing = True
            context.idempotent_replay = True
            logger.info(
                'execute_action idempotent_replay job=%s action=%s log=%s',
                job_id,
                action_code,
                getattr(context.action_log, 'log_id', None),
            )
            return self._response_service.build_execute_result(
                context,
                request=request,
            )

        # 6–7. stale + Action Master (reconciled overlay authority)
        validation = self._validation_service.validate_pre_execute_after_idempotency(
            context,
            request=request,
            idempotency_keys=keys,
        )

        # 8. evidence + media security
        self._evidence_service.validate_required_evidence(context)

        if not context.operation_action:
            context.operation_action = self._validation_service.resolve_operation_action(
                context,
            )

        # 9. pessimistic locks before mutation
        lock_execution_entities(
            context,
            operation_action=context.operation_action,
        )

        # 10. kernel under reconciled overlay (GET ≡ POST authority)
        exec_result = self._execute_kernel(
            context,
            tenant_user=tenant_user,
            request=request,
        )
        context.action_log = exec_result.action_log
        context.reused_existing = exec_result.reused_existing
        context.idempotent_replay = exec_result.reused_existing

        # 11. media (same transaction; rolls back with kernel on failure)
        self._media_service.persist_execution_media(context)

        # 12. post reconcile + response
        return self._response_service.build_execute_result(
            context,
            request=request,
        )

    def _execute_kernel(
        self,
        context: ExecuteActionContext,
        *,
        tenant_user: Any | None,
        request: Any | None,
    ):
        """Invoke ``ActionExecutionService`` inside guard + reconciled status overlay."""
        payload = context.payload or {}
        jwt_payload = getattr(request, 'mobile_jwt_payload', None) if request else None
        if jwt_payload is None and request is not None:
            from mobile_api.rbac import get_mobile_jwt_payload

            jwt_payload = get_mobile_jwt_payload(request)

        driver_pk = getattr(context.driver, 'pk', None) or getattr(
            context.driver,
            'driver_id',
            None,
        )
        guard_ctx = MobileExecutionContext(
            driver=context.driver,
            tenant_user=tenant_user,
            tenant_schema=context.tenant_schema,
            driver_id=str(driver_pk or ''),
            user_id=context.user_id,
            jwt_driver_id=str((jwt_payload or {}).get('driver_id') or '') or None,
        )

        booking_item_type = self._validation_service._booking_item_type(context)
        truck = self._resolve_truck(context)
        created_by_label = self._driver_label(context.driver)

        try:
            with mobile_execution_guard(guard_ctx):
                with kernel_validation_overlay(context):
                    return ActionExecutionService.execute_driver_action(
                        operation_action=context.operation_action,
                        booking=context.booking,
                        shipment=context.shipment,
                        movement=context.movement,
                        truck=truck,
                        driver=context.driver,
                        tenant_user=tenant_user,
                        created_by_label=created_by_label,
                        notes=str(payload.get('notes') or ''),
                        source='Mobile',
                        source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                        source_ref=context.source_ref,
                        idempotency_key=context.idempotency_key,
                        booking_item_type=booking_item_type,
                        latitude=str(payload.get('latitude') or ''),
                        longitude=str(payload.get('longitude') or ''),
                        map_link=str(payload.get('map_link') or ''),
                        birth_booking_item_type=booking_item_type,
                        skip_recent_duplicate_guard=True,
                        sync_shipment_after=True,
                        mobile_cod_amount=payload.get('mobile_cod_amount'),
                    )
        except DjangoValidationError as exc:
            logger.warning(
                'execute_kernel_validation_failed job=%s action=%s err=%s',
                context.job_id,
                context.action_code,
                exc,
            )
            message = '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)
            body = build_validation_error(
                error_code='execution_validation_failed',
                message=message,
                refresh_required=True,
            )
            raise ExecuteActionError(
                message,
                code='execution_validation_failed',
                http_status=400,
                message_key='mobile.jobs.execute.execution_validation_failed',
                refresh_required=True,
                validation_error=body,
            ) from exc

    @staticmethod
    def _resolve_truck(context: ExecuteActionContext) -> Any:
        if context.shipment is not None:
            return getattr(context.shipment, 'truck', None)
        if context.movement is not None:
            return getattr(context.movement, 'truck', None)
        return None

    @staticmethod
    def _driver_label(driver: Any) -> str:
        if driver is None:
            return ''
        for attr in ('driver_name', 'full_name', 'name'):
            value = getattr(driver, attr, None)
            if value:
                return str(value)[:200]
        return str(getattr(driver, 'driver_no', '') or getattr(driver, 'pk', ''))[:200]

    @staticmethod
    def _normalize_job_type(job_type: str) -> JobType:
        raw = (job_type or '').strip().lower()
        if raw in ('shipment', 'shipments'):
            return 'shipment'
        if raw in ('movement', 'movements', 'empty_move', 'empty_moves'):
            return 'movement'
        raise ExecuteActionError(
            f'Invalid job_type: {job_type!r}',
            code='invalid_job_type',
            http_status=400,
            message_key='mobile.validation.failed',
        )
