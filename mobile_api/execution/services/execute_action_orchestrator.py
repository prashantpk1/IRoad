"""
mobile_api/execution/services/execute_action_orchestrator.py

Main orchestrator for the Unified Execute Action API (shipment + empty move).

Delegates all mutations to ``iroad_tenants.services.ActionExecutionService``;
this module owns mobile boundary concerns only (resolve, reconcile overlay,
evidence, stale sync, response projection).
"""
from __future__ import annotations

import logging
from decimal import Decimal
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
    extract_capture_bundle_id,
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
from mobile_api.execution.services.a7_pod_evidence_resolver import (
    prepare_a7_execute_evidence,
    promote_merged_a7_media,
)
from mobile_api.execution.services.execution_validation_service import (
    ExecutionValidationService,
)
from mobile_api.hard_pod.services.hard_pod_execute_integration import (
    HardPodExecuteIntegrationService,
)
from mobile_api.helpers.mobile_execution_guard import (
    MobileExecutionContext,
    mobile_execution_guard,
)
from mobile_api.job_detail.services.movement_job_resolver import MovementJobResolver
from mobile_api.job_detail.services.shipment_job_resolver import ShipmentJobResolver
from tenant_workspace.models import DriverTreasuryTransaction
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
        self._hard_pod_integration = HardPodExecuteIntegrationService()

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

        # 7.5 A7 — merge fragmented POD captures (photo / video) before evidence checks
        prepare_a7_execute_evidence(context, request=request)

        # 8. evidence + media security
        self._evidence_service.validate_required_evidence(context)

        if not context.operation_action:
            context.operation_action = self._validation_service.resolve_operation_action(
                context,
            )

        # 8.5 payment bundle staging integration (read-only validation)
        self._attach_payment_bundle_for_cod(context)

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
        self._sync_context_from_action_log(context)

        hard_pod_submission = self._hard_pod_integration.bind_action_log(
            context,
            exec_result.action_log,
        )
        if hard_pod_submission is not None:
            context.resolver_meta = dict(context.resolver_meta or {})
            context.resolver_meta['hard_pod_custody_submission_id'] = str(hard_pod_submission.pk)
            context.resolver_meta['hard_pod_promotion_action_log_id'] = hard_pod_submission.promotion_action_log_id

        # 11. media / POD bundle promotion (same transaction; rolls back with kernel)
        bundle_id = extract_capture_bundle_id(context.payload)
        if bundle_id:
            self._promote_pod_capture_bundle(context, bundle_id=bundle_id)
        else:
            self._media_service.persist_execution_media(context)

        # 12. post reconcile + response
        result = self._response_service.build_execute_result(
            context,
            request=request,
        )
        result = self._attach_pod_capture_to_result(result, context)
        result = self._attach_payment_collection_to_result(result, context)
        return self._attach_hard_pod_custody_to_result(result, context)

    def _attach_payment_bundle_for_cod(self, context: ExecuteActionContext) -> None:
        """
        COD collection (A9): resolve amount for treasury side effects.

        When a staged ``PaymentCollectionBundle`` exists (prep API), it is the
        source of truth for amount and variance. Otherwise the driver may post
        ``mobile_cod_amount`` directly on Execute Action (normal mobile flow).
        """
        if context.idempotent_replay:
            return
        action = context.operation_action
        if not self._is_collect_payment_action(action):
            return
        if context.shipment is None:
            return
        if (getattr(context.shipment, 'order_type', '') or '').upper() != 'COD':
            return

        from decimal import Decimal
        from django.db import connection

        from mobile_api.execution.exceptions import ExecuteActionError
        from mobile_api.payment_collection.models import PaymentCollectionBundle

        tenant_schema = (context.tenant_schema or '').strip() or getattr(connection, 'schema_name', '')
        driver_pk = EvidenceValidationService._driver_pk(context.driver)
        shipment_pk = EvidenceValidationService._shipment_key(context)
        idempotency_key = (
            (context.idempotency_key or '').strip()
            or str((context.payload or {}).get('client_action_id') or '').strip()
        )
        if not (tenant_schema and driver_pk and shipment_pk and idempotency_key):
            return

        bundle = (
            PaymentCollectionBundle.objects.filter(
                tenant_schema=tenant_schema,
                driver_id=driver_pk,
                client_payment_id=idempotency_key,
            )
            .order_by('-created_at')
            .first()
        )
        context.payload = dict(context.payload or {})

        if bundle is None:
            raw_amount = context.payload.get('mobile_cod_amount')
            if raw_amount is None or str(raw_amount).strip() == '':
                raise ExecuteActionError(
                    'COD collection requires mobile_cod_amount or a staged payment bundle.',
                    code='mobile_cod_amount_required',
                    http_status=400,
                    message_key='mobile.jobs.execute.mobile_cod_amount_required',
                    refresh_required=True,
                )
            try:
                collected = Decimal(str(raw_amount))
            except Exception as exc:
                raise ExecuteActionError(
                    'Invalid mobile_cod_amount for COD collection.',
                    code='invalid_mobile_cod_amount',
                    http_status=400,
                    message_key='mobile.validation.failed',
                    refresh_required=True,
                ) from exc
            if collected <= 0:
                raise ExecuteActionError(
                    'mobile_cod_amount must be greater than zero.',
                    code='invalid_mobile_cod_amount',
                    http_status=400,
                    message_key='mobile.validation.failed',
                    refresh_required=True,
                )
            context.payload['mobile_cod_amount'] = collected
            expected = Decimal(
                str(getattr(context.shipment, 'cod_amount', None) or Decimal('0'))
            )
            context.resolver_meta = dict(context.resolver_meta or {})
            context.resolver_meta['payment_collection_variance'] = (
                ExecuteActionOrchestrator._build_payment_variance_from_amounts(
                    collected,
                    expected,
                )
            )
            return

        # Scope checks: wrong bundle/shipment should hard fail.
        if (bundle.shipment_id or '').strip() != shipment_pk:
            raise ExecuteActionError(
                'Payment bundle does not match shipment.',
                code='payment_bundle_shipment_mismatch',
                http_status=409,
                message_key='mobile.payment_collection.bundle_shipment_mismatch',
                refresh_required=True,
            )

        # Staged bundle is source of truth for Action 9 treasury posting.
        context.payload['mobile_cod_amount'] = Decimal(str(bundle.amount))

        context.resolver_meta = dict(context.resolver_meta or {})
        context.resolver_meta['payment_collection_bundle'] = bundle
        context.resolver_meta['payment_collection_variance'] = self._build_payment_variance(bundle)

    @staticmethod
    def _attach_payment_collection_to_result(
        result: ExecuteActionResult,
        context: ExecuteActionContext,
    ) -> ExecuteActionResult:
        bundle = (context.resolver_meta or {}).get('payment_collection_bundle')
        if not bundle:
            return result
        payload = dict(result.payload)
        payment_bundle = {
            'bundle_id': str(getattr(bundle, 'id', '') or ''),
            'client_payment_id': (getattr(bundle, 'client_payment_id', None) or '').strip(),
            'shipment_id': (getattr(bundle, 'shipment_id', None) or '').strip(),
            'driver_id': (getattr(bundle, 'driver_id', None) or '').strip(),
            'amount': str(getattr(bundle, 'amount', '') or ''),
            'expected_amount': str(getattr(bundle, 'expected_amount', '') or ''),
            'variance_detected': bool(getattr(bundle, 'variance_detected', False)),
            'payment_mode': (getattr(bundle, 'payment_mode', None) or '').strip(),
        }
        pod_cod = dict(payload.get('pod_cod') or {})
        treasury_pending = bool(pod_cod.get('treasury_pending')) if isinstance(pod_cod, dict) else False
        cod_collected = bool(pod_cod.get('cod_collected')) if isinstance(pod_cod, dict) else False
        payload['payment_bundle'] = payment_bundle
        treasury_status = {
            'treasury_pending': treasury_pending,
        }
        cod_status = {
            'cod_collected': cod_collected,
        }
        payload['treasury_status'] = treasury_status
        payload['cod_status'] = cod_status

        # Execute Action API response serializer only exposes `pod_cod`,
        # so we also nest payment/tax status inside `pod_cod`.
        pod_cod_payload = dict(payload.get('pod_cod') or {})
        pod_cod_payload.setdefault('payment_bundle', payment_bundle)
        pod_cod_payload.setdefault('treasury_status', treasury_status)
        pod_cod_payload.setdefault('cod_status', cod_status)
        payload['pod_cod'] = pod_cod_payload

        treasury_txn = None
        if context.action_log is not None:
            treasury_txn = (
                DriverTreasuryTransaction.objects.filter(operation_action_log=context.action_log)
                .order_by('-transaction_date', '-created_at')
                .first()
            )

        variance = (context.resolver_meta or {}).get('payment_collection_variance')
        if variance is None and bundle is not None:
            variance = ExecuteActionOrchestrator._build_payment_variance(bundle)

        payload['success'] = True
        payload['action'] = str(getattr(context.operation_action, 'action_code', '') or context.action_code or '')
        payload['shipment_id'] = str(getattr(context.shipment, 'pk', '') or getattr(context.shipment, 'shipment_id', '') or '')
        payload['cod_payment_status'] = str(getattr(context.shipment, 'collection_status', '') or '')
        payload['treasury_transaction_id'] = str(getattr(treasury_txn, 'transaction_id', '') or '') if treasury_txn else ''
        payload['variance'] = variance
        return ExecuteActionResult(payload=payload, http_status=result.http_status)

    @staticmethod
    def _is_collect_payment_action(action_master_row: Any | None) -> bool:
        return bool(
            action_master_row is not None
            and bool(getattr(action_master_row, 'auto_treasury_post', False))
            and str(getattr(action_master_row, 'action_scope', '') or '').strip().casefold() == 'job'
            and int(getattr(action_master_row, 'sequence_number', 0) or 0) == 9
        )

    @staticmethod
    def _build_payment_variance(bundle: Any) -> dict[str, Any] | None:
        collected = Decimal(str(getattr(bundle, 'amount', 0) or 0))
        expected = Decimal(str(getattr(bundle, 'expected_amount', 0) or 0))
        return ExecuteActionOrchestrator._build_payment_variance_from_amounts(
            collected,
            expected,
        )

    @staticmethod
    def _build_payment_variance_from_amounts(
        collected: Decimal,
        expected: Decimal,
    ) -> dict[str, Any] | None:
        if collected == expected:
            return {
                'has_variance': False,
                'variance_type': 'none',
                'variance_amount': '0.00',
                'expected': str(expected),
                'collected': str(collected),
                'message': 'No variance detected.',
            }
        variance_amount = collected - expected
        variance_type = 'short' if variance_amount < 0 else 'over'
        return {
            'has_variance': True,
            'variance_type': variance_type,
            'variance_amount': str(abs(variance_amount)),
            'expected': str(expected),
            'collected': str(collected),
            'message': 'Variance recorded. Operations team will follow up.',
        }

    def _attach_hard_pod_custody_to_result(
        self,
        result: ExecuteActionResult,
        context: ExecuteActionContext,
    ) -> ExecuteActionResult:
        submission = (context.resolver_meta or {}).get('hard_pod_custody_submission')
        authority = (context.resolver_meta or {}).get('hard_pod_custody_authority')
        if not submission:
            return result

        payload = dict(result.payload)
        hard_pod = {
            'submission_id': str(getattr(submission, 'pk', '') or ''),
            'client_submission_id': (getattr(submission, 'client_submission_id', None) or '').strip(),
            'shipment_id': (getattr(submission, 'shipment_id', None) or '').strip(),
            'driver_id': (getattr(submission, 'driver_id', None) or '').strip(),
            'promoted_at': getattr(submission, 'promoted_at', None).isoformat() if getattr(submission, 'promoted_at', None) else None,
            'promotion_action_log_id': (getattr(submission, 'promotion_action_log_id', None) or '').strip(),
            'custody_authority': dict(authority or {}),
        }
        pod_cod = dict(payload.get('pod_cod') or {})
        pod_cod.setdefault('hard_pod', hard_pod)
        payload['pod_cod'] = pod_cod
        payload['hard_pod'] = hard_pod
        return ExecuteActionResult(payload=payload, http_status=result.http_status)

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
    def _sync_context_from_action_log(context: ExecuteActionContext) -> None:
        action_log = context.action_log
        if action_log is None:
            return
        shipment = getattr(action_log, 'shipment', None)
        movement = getattr(action_log, 'truck_movement', None)
        if shipment is not None:
            context.shipment = shipment
            context.booking = getattr(shipment, 'booking', None) or context.booking
        if movement is not None:
            context.movement = movement

    @staticmethod
    def _driver_label(driver: Any) -> str:
        if driver is None:
            return ''
        for attr in ('driver_name', 'full_name', 'name'):
            value = getattr(driver, attr, None)
            if value:
                return str(value)[:200]
        return str(getattr(driver, 'driver_no', '') or getattr(driver, 'pk', ''))[:200]

    def _promote_pod_capture_bundle(
        self,
        context: ExecuteActionContext,
        *,
        bundle_id: str,
    ) -> None:
        """
        After Action Log insert: append immutable staged media and mark bundle promoted.

        Skipped on execute idempotent replay (Action Log already linked).
        """
        if context.idempotent_replay or context.action_log is None:
            return

        from mobile_api.pod_capture.dto.promotion_models import (
            PodPromotionRequest,
            PodPromotionScope,
        )
        from mobile_api.pod_capture.exceptions import PodCaptureError
        from mobile_api.pod_capture.staging.evidence_promotion_service import (
            EvidencePromotionService,
            staged_media_to_action_log_items,
        )

        driver_pk = EvidenceValidationService._driver_pk(context.driver)
        shipment_key = EvidenceValidationService._shipment_key(context)
        scope = PodPromotionScope(
            tenant_schema=(context.tenant_schema or '').strip(),
            driver_id=driver_pk,
            shipment_id=shipment_key,
        )

        try:
            promotion = EvidencePromotionService().promote_staged_bundle(
                PodPromotionRequest(
                    bundle_id=bundle_id,
                    action_log=context.action_log,
                    scope=scope,
                ),
                promoted_by=self._driver_label(context.driver),
                execution_idempotency_key=str(
                    (context.payload or {}).get('client_action_id') or ''
                ).strip(),
            )
        except PodCaptureError as exc:
            raise EvidenceValidationService._map_pod_capture_error(exc) from exc

        promote_merged_a7_media(
            context,
            primary_bundle_id=bundle_id,
            action_log=context.action_log,
        )

        staging = EvidencePromotionService()._staging  # noqa: SLF001
        media_rows = staging.get_media(bundle_id)
        promoted_media = [
            {
                'media_id': row.media_id,
                'media_type': row.media_type,
                'file_ref': row.file_ref,
                'line_no': row.line_no,
                'action_log_media_id': media_id,
            }
            for row, media_id in zip(
                media_rows,
                promotion.media_row_ids,
                strict=False,
            )
        ]
        if len(promoted_media) != len(promotion.media_row_ids):
            items = staged_media_to_action_log_items(media_rows)
            promoted_media = [
                {
                    'media_type': item.media_type,
                    'file_ref': item.file_ref,
                    'line_no': item.line_no,
                    'action_log_media_id': str(pk),
                }
                for item, pk in zip(items, promotion.media_row_ids, strict=False)
            ]

        compliance = self._build_pod_capture_compliance_summary(context)
        context.resolver_meta = dict(context.resolver_meta or {})
        context.resolver_meta['pod_capture_promotion'] = {
            'promoted_bundle_id': promotion.bundle_id,
            'promoted_media': promoted_media,
            'compliance': compliance,
            'replayed': promotion.replayed,
            'media_row_ids': promotion.media_row_ids,
        }

    @staticmethod
    def _build_pod_capture_compliance_summary(
        context: ExecuteActionContext,
    ) -> dict[str, Any]:
        requirements = dict(context.resolver_meta.get('pod_capture_compliance') or {})
        payload = context.payload or {}
        return {
            'validated': bool(requirements),
            'pod_type': str(payload.get('pod_type') or '').strip() or None,
            'target_action_code': (context.action_code or '').strip() or None,
            'requirements': {
                'gps': bool(requirements.get('gps')),
                'photo': bool(requirements.get('photo')),
                'photo_min_count': int(requirements.get('photo_min_count') or 0),
                'video': bool(requirements.get('video')),
                'signature': bool(requirements.get('signature')),
                'note_required': bool(requirements.get('note_required')),
            },
            'bundle_status': _bundle_status_value(
                context.resolver_meta.get('pod_capture_bundle'),
            ),
        }

    @staticmethod
    def _attach_pod_capture_to_result(
        result: ExecuteActionResult,
        context: ExecuteActionContext,
    ) -> ExecuteActionResult:
        promotion = (context.resolver_meta or {}).get('pod_capture_promotion')
        if not promotion:
            return result
        payload = dict(result.payload)
        payload['pod_capture'] = {
            'promoted_bundle_id': promotion.get('promoted_bundle_id'),
            'promoted_media': list(promotion.get('promoted_media') or []),
            'compliance': dict(promotion.get('compliance') or {}),
            'replayed': bool(promotion.get('replayed')),
        }
        return ExecuteActionResult(payload=payload, http_status=result.http_status)

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


def _bundle_status_value(bundle: Any) -> str | None:
    if bundle is None:
        return None
    status = getattr(bundle, 'status', None)
    if status is None:
        return None
    return getattr(status, 'value', str(status))
