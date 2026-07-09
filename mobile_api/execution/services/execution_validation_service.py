"""
mobile_api/execution/services/execution_validation_service.py

Pre-kernel validation — Action Master authority with reconciled overlays.

Must align with Job Detail GET ``allowed_actions`` (same engine + overlay).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.utils.translation import gettext_lazy as _

from iroad_tenants.services.operation_execution_service import OperationExecutionService
from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.dto.execution_authoritative_context import (
    ExecutionAuthoritativeContext,
)
from mobile_api.execution.dto.execution_validation_error import build_validation_error
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.guards.execution_idempotency_guard import (
    ExecutionIdempotencyGuard,
    IdempotencyKeys,
)
from mobile_api.execution.guards.stale_execution_guard import StaleExecutionGuard
from mobile_api.execution.services.execution_reconcile_service import (
    ExecutionReconcileService,
)
from mobile_api.hard_pod.services.hard_pod_execute_integration import (
    HardPodExecuteIntegrationService,
)
from mobile_api.job_detail.helpers.booking_job_context import (
    resolve_pending_booking_item_type,
)
from mobile_api.job_detail.projections.workflow_projection import build_workflow_section
from mobile_api.execution.services.execution_context_adapter import (
    finalize_execute_scope,
    to_job_detail_context,
)
from mobile_api.utils.next_action_hint_builder import build_next_action_hint
from tenant_workspace.models import TenantOperationAction


@dataclass(frozen=True)
class ExecutionValidationResult:
    """Outcome of pre-execute validation."""

    ok: bool = True
    idempotent_replay: bool = False
    idempotency_keys: IdempotencyKeys | None = None


class ExecutionValidationService:
    """
    Validate execute requests before ``ActionExecutionService.execute_driver_action``.

    Order:
      1. Idempotency key required + normalized
      2. Idempotent replay detection (safe retry)
      3. Stale workflow / content_hash / entity_versions
      4. Action Master exists + policy allowed + membership in allowed_actions
    """

    def __init__(
        self,
        *,
        idempotency_guard: ExecutionIdempotencyGuard | None = None,
        stale_guard: StaleExecutionGuard | None = None,
        reconcile_service: ExecutionReconcileService | None = None,
        operation_action_model: type = TenantOperationAction,
    ) -> None:
        self._idempotency = idempotency_guard or ExecutionIdempotencyGuard()
        self._stale = stale_guard or StaleExecutionGuard()
        self._reconcile = reconcile_service or ExecutionReconcileService()
        self._operation_action_model = operation_action_model
        self._hard_pod_integration = HardPodExecuteIntegrationService()

    def validate_pre_execute(
        self,
        context: ExecuteActionContext,
        *,
        request: Any | None = None,
    ) -> ExecutionValidationResult:
        """
        Run full validation pipeline (includes idempotency — prefer orchestrator path).

        Raises:
            ExecuteActionError: Structured ``validation_error`` on failure.
        """
        keys = self._idempotency.normalize_request_keys(context)
        if self._idempotency.detect_idempotent_replay(context, keys):
            return ExecutionValidationResult(
                ok=True,
                idempotent_replay=True,
                idempotency_keys=keys,
            )
        return self.validate_pre_execute_after_idempotency(
            context,
            request=request,
            idempotency_keys=keys,
        )

    def validate_pre_execute_after_idempotency(
        self,
        context: ExecuteActionContext,
        *,
        request: Any | None = None,
        idempotency_keys: IdempotencyKeys | None = None,
    ) -> ExecutionValidationResult:
        """
        Stale + Action Master validation when idempotency replay did not short-circuit.

        Caller must have normalized keys and ruled out replay already.
        """
        _ = idempotency_keys
        self._stale.assert_not_stale(context)
        self.validate_action_master(context, request=request)
        self._validate_pod_shipment_document(context)
        _ = ExecutionAuthoritativeContext.from_execute_context(context)
        self._validate_hard_pod_execute_requirements(context)
        self._attach_operational_issue_warnings(context)
        return ExecutionValidationResult(
            ok=True,
            idempotent_replay=False,
            idempotency_keys=idempotency_keys,
        )

    def validate_action_master(
        self,
        context: ExecuteActionContext,
        *,
        request: Any | None = None,
    ) -> None:
        """Resolve Action Master row and assert policy + allowed_actions membership."""
        finalize_execute_scope(context)
        operation_action = self.resolve_operation_action(context)
        context.operation_action = operation_action

        with self._reconcile.apply_status_overlays(context):
            policy_error = self._policy_validate(context, operation_action)
            if policy_error:
                raise self._forbidden_action(
                    policy_error,
                    context=context,
                    request=request,
                )

            if not self._action_in_allowed_list(context, operation_action, request=request):
                raise self._forbidden_action(
                    str(_('mobile.jobs.execute.action_not_allowed')),
                    context=context,
                    request=request,
                )

    def _validate_pod_shipment_document(self, context: ExecuteActionContext) -> None:
        from django.core.exceptions import ValidationError as DjangoValidationError

        from iroad_tenants.operation_runtime.pod_action import (
            validate_shipment_document_for_pod_execute,
        )
        from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
            is_pod_upload_action,
        )

        action = context.operation_action
        shipment = context.shipment
        if action is None or shipment is None:
            return
        if not (
            is_pod_upload_action(action) or getattr(action, 'auto_pod_post', False)
        ):
            return
        try:
            validate_shipment_document_for_pod_execute(shipment, action)
        except DjangoValidationError as exc:
            message = '; '.join(getattr(exc, 'messages', []) or [str(exc)])
            raise self._validation_error(
                error_code='shipment_document_required',
                message=message,
                refresh_required=False,
                http_status=400,
            ) from exc

    def resolve_operation_action(self, context: ExecuteActionContext) -> Any:
        """Load active Action Master row for ``context.action_code``."""
        code = (context.action_code or '').strip()
        if not code:
            raise self._validation_error(
                error_code='action_code_required',
                message=str(_('mobile.jobs.execute.action_code_required')),
                refresh_required=False,
                http_status=400,
            )

        row = (
            self._operation_action_model.objects.filter(
                action_code__iexact=code,
                status=TenantOperationAction.Status.ACTIVE,
            )
            .first()
        )
        if row is None:
            raise self._validation_error(
                error_code='action_not_found',
                message=str(_('mobile.jobs.execute.action_not_found')),
                refresh_required=True,
                http_status=404,
            )
        return row

    def _action_in_allowed_list(
        self,
        context: ExecuteActionContext,
        operation_action: Any,
        *,
        request: Any | None = None,
    ) -> bool:
        """
        Membership check against the same allowed_actions list as Job Detail GET.

        Uses ``context.authoritative`` when present; otherwise rebuilds workflow under overlay.
        """
        allowed_codes = self._allowed_action_codes(context, request=request)
        code = str(getattr(operation_action, 'action_code', '') or context.action_code or '')
        code = code.strip()
        if not code:
            return False
        normalized = {c.casefold() for c in allowed_codes if c}
        if code.casefold() in normalized:
            return True
        if self._combined_pod_execute_allowed(context, operation_action):
            return True
        if self._pod_digital_recovery_execute_allowed(context, operation_action):
            return True
        if self._collect_payment_execute_allowed(context, operation_action):
            return True
        if self._job_close_execute_allowed(context, operation_action):
            return True
        if self._hard_pod_promotion_execute_allowed(context, operation_action):
            return True
        if self._hard_pod_promoted_custody_replay_allowed(context, operation_action):
            return True
        return self._hard_copy_execute_allowed(context, operation_action)

    def _hard_pod_promotion_execute_allowed(
        self,
        context: ExecuteActionContext,
        operation_action: Any,
    ) -> bool:
        """Label-only POD (OA-0009) step 2 — align allowed list with policy bypass."""
        from iroad_tenants.operation_execution import (
            _hard_pod_post_digital_promotion_allowed,
        )

        if context.shipment is None:
            return False
        if not _hard_pod_post_digital_promotion_allowed(
            operation_action,
            context.shipment,
        ):
            return False
        policy_error = self._policy_validate(context, operation_action)
        return policy_error is None

    def _hard_pod_promoted_custody_replay_allowed(
        self,
        context: ExecuteActionContext,
        operation_action: Any,
    ) -> bool:
        """Custody already promoted — safe idempotent replay for hard-copy execute."""
        from iroad_tenants.operation_execution import (
            _hard_pod_custody_promoted,
            _is_hard_pod_kernel_promotion_action,
        )

        if context.shipment is None:
            return False
        if not _is_hard_pod_kernel_promotion_action(operation_action):
            return False
        if not _hard_pod_custody_promoted(context.shipment):
            return False
        submission_id = self._custody_submission_id_from_context(context)
        if not submission_id:
            return False
        try:
            from mobile_api.hard_pod.models import HardPODCustodySubmission

            submission = (
                HardPODCustodySubmission.objects.filter(pk=submission_id)
                .first()
            )
        except Exception:
            return False
        if submission is None:
            return False
        if not (
            getattr(submission, 'promoted_at', None)
            and (submission.promotion_action_log_id or '').strip()
        ):
            return False
        return True

    @staticmethod
    def _custody_submission_id_from_context(context: ExecuteActionContext) -> str:
        payload = context.payload or {}
        return str(
            payload.get('custody_submission_id')
            or context.resolver_meta.get('hard_pod_custody_submission_id')
            or ''
        ).strip()

    def _policy_validate(
        self,
        context: ExecuteActionContext,
        operation_action: Any,
    ) -> str | None:
        return OperationExecutionService.validate_operation_action_allowed(
            operation_action,
            booking=context.booking,
            shipment=context.shipment,
            movement=context.movement,
            booking_item_type=self._booking_item_type(context),
            hard_pod_custody_submission_id=self._custody_submission_id_from_context(
                context
            ),
        )

    def _pod_digital_recovery_execute_allowed(
        self,
        context: ExecuteActionContext,
        operation_action: Any,
    ) -> bool:
        """POD capture after credit unloading marked Delivered before digital evidence."""
        from iroad_tenants.operation_execution import (
            _combined_pod_allows_digital_recovery,
        )
        from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
            is_pod_upload_action,
        )

        if context.shipment is None:
            return False
        if not _combined_pod_allows_digital_recovery(
            operation_action,
            context.shipment,
        ):
            return False
        if not (
            is_pod_upload_action(operation_action)
            or getattr(operation_action, 'auto_pod_post', False)
        ):
            return False
        policy_error = self._policy_validate(context, operation_action)
        return policy_error is None

    def _collect_payment_execute_allowed(
        self,
        context: ExecuteActionContext,
        operation_action: Any,
    ) -> bool:
        """Payment Collection may be absent from workflow list while still policy-valid."""
        from iroad_tenants.operation_execution import _is_collect_payment_action

        if context.shipment is None or not _is_collect_payment_action(operation_action):
            return False
        policy_error = self._policy_validate(context, operation_action)
        return policy_error is None

    def _job_close_execute_allowed(
        self,
        context: ExecuteActionContext,
        operation_action: Any,
    ) -> bool:
        """End Job may be absent from workflow list while still policy-valid."""
        from iroad_tenants.operation_execution import _is_job_close_action

        if context.shipment is None or not _is_job_close_action(operation_action):
            return False
        policy_error = self._policy_validate(context, operation_action)
        return policy_error is None

    def _combined_pod_execute_allowed(
        self,
        context: ExecuteActionContext,
        operation_action: Any,
    ) -> bool:
        """Upload POD step 2 — hard-copy custody promotion after digital execute."""
        from iroad_tenants.operation_execution import (
            _combined_pod_allows_hard_copy_retry,
            _is_combined_upload_pod_action,
        )
        from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
            is_pod_upload_action,
        )

        if context.shipment is None:
            return False
        if not _combined_pod_allows_hard_copy_retry(
            operation_action,
            context.shipment,
        ):
            return False
        if not (
            _is_combined_upload_pod_action(operation_action)
            or is_pod_upload_action(operation_action)
        ):
            return False
        policy_error = self._policy_validate(context, operation_action)
        return policy_error is None

    def _hard_copy_execute_allowed(
        self,
        context: ExecuteActionContext,
        operation_action: Any,
    ) -> bool:
        """A7H runs inside Upload POD — allowed when policy permits, not in workflow list."""
        from iroad_tenants.operation_execution import (
            _hard_copy_collection_shipment_allowed,
            _is_hard_copy_collection_action,
        )

        if not _is_hard_copy_collection_action(operation_action):
            return False
        if context.shipment is None:
            return False
        if not _hard_copy_collection_shipment_allowed(context.shipment):
            return False
        policy_error = self._policy_validate(context, operation_action)
        return policy_error is None

    def _allowed_action_codes(
        self,
        context: ExecuteActionContext,
        *,
        request: Any | None = None,
    ) -> set[str]:
        auth = context.authoritative or {}
        actions = list(auth.get('allowed_actions') or [])
        if not actions:
            workflow = context.workflow or {}
            actions = list(workflow.get('allowed_actions') or [])

        if not actions:
            job_detail_ctx = to_job_detail_context(context)
            workflow = build_workflow_section(job_detail_ctx, request=request)
            actions = list(workflow.get('allowed_actions') or [])
            context.workflow = workflow

        codes: set[str] = set()
        for item in actions:
            if isinstance(item, dict):
                token = str(item.get('action_code') or '').strip()
                if token:
                    codes.add(token)
        return codes

    @staticmethod
    def _attach_operational_issue_warnings(context: ExecuteActionContext) -> None:
        """
        Advisory operational issue overlay — never blocks kernel execute.

        Surfaces escalation alerts and blocking recommendations for Action Master policy later.
        """
        from mobile_api.job_detail.projections.job_detail_projection_builder import (
            attach_operational_issue_warnings_to_execute_context,
        )

        attach_operational_issue_warnings_to_execute_context(context)

    def _validate_hard_pod_execute_requirements(self, context: ExecuteActionContext) -> None:
        self._hard_pod_integration.validate_execute_requirements(context)

    @staticmethod
    def _booking_item_type(context: ExecuteActionContext) -> str:
        if context.job_type == 'booking' and context.booking is not None:
            return resolve_pending_booking_item_type(
                context.booking,
                driver=context.driver,
            )
        if context.shipment is not None and context.booking is not None:
            from mobile_api.helpers.backload_booking_redirect import (
                should_pivot_shipment_to_backload_booking,
            )

            if should_pivot_shipment_to_backload_booking(
                driver=context.driver,
                booking=context.booking,
                shipment=context.shipment,
            ):
                return resolve_pending_booking_item_type(
                    context.booking,
                    driver=context.driver,
                )
        if context.shipment is not None:
            return str(
                getattr(context.shipment, 'booking_item_type', '') or ''
            ).strip()
        if context.booking is not None:
            return resolve_pending_booking_item_type(
                context.booking,
                driver=context.driver,
            )
        return ''

    @staticmethod
    def _build_next_action_hint_for_context(
        context: ExecuteActionContext,
        *,
        request: Any | None = None,
    ) -> dict[str, Any]:
        _ = request
        order_type = ''
        if context.shipment is not None:
            order_type = str(getattr(context.shipment, 'order_type', '') or '')
        return build_next_action_hint(
            workflow=dict(context.workflow or {}),
            pod_cod=dict(context.pod_cod or {}),
            action_code=context.action_code,
            order_type=order_type,
            shipment=context.shipment,
            booking=context.booking,
            driver=context.driver,
            movement=context.movement,
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
        )

    @staticmethod
    def _forbidden_action(
        message: str,
        *,
        context: ExecuteActionContext | None = None,
        request: Any | None = None,
    ) -> ExecuteActionError:
        next_hint: dict[str, Any] | None = None
        if context is not None:
            next_hint = ExecutionValidationService._build_next_action_hint_for_context(
                context,
                request=request,
            )
        body = build_validation_error(
            error_code='action_not_allowed',
            message=message,
            refresh_required=True,
            next_action_hint=next_hint,
        )
        return ExecuteActionError(
            message,
            code='action_not_allowed',
            http_status=403,
            message_key='mobile.jobs.execute.action_not_allowed',
            refresh_required=True,
            validation_error=body,
        )

    @staticmethod
    def _validation_error(
        *,
        error_code: str,
        message: str,
        refresh_required: bool,
        http_status: int,
    ) -> ExecuteActionError:
        body = build_validation_error(
            error_code=error_code,
            message=message,
            refresh_required=refresh_required,
        )
        return ExecuteActionError(
            message,
            code=error_code,
            http_status=http_status,
            message_key=f'mobile.jobs.execute.{error_code}',
            refresh_required=refresh_required,
            validation_error=body,
        )

    # Back-compat aliases
    validate_allowed_action = validate_action_master
