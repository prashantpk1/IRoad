"""
Driver execute-action — transactional pipeline via ActionExecutionService.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _

from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
from iroad_tenants.services.action_execution_service import ActionExecutionService
from iroad_tenants.services.latest_state_service import LatestStateService
from mobile_api.helpers.action_execution_validation import validate_mobile_execution_payload
from mobile_api.helpers.action_log_media import save_action_log_media_from_mobile_request
from mobile_api.helpers.i18n import get_localized_value
from mobile_api.helpers.job_detail_guards import job_detail_log_scan_limit
from mobile_api.helpers.job_detail_observability import (
    execution_transaction_timer,
    record_execution_outcome,
)
from mobile_api.helpers.job_detail_perf import (
    load_scoped_action_logs,
    lock_entities_for_execution,
    reconcile_movement_state_from_logs,
    reconcile_shipment_state_from_logs,
)
from mobile_api.helpers.execution_workflow_cache import (
    get_allowed_driver_actions_cached,
    invalidate_allowed_actions_cache,
)
from mobile_api.helpers.job_execution_security import (
    SecureJobExecutionContext,
    authorize_driver_action_execution,
    require_execution_context,
    secure_load_movement_for_execution,
    secure_load_shipment_for_execution,
    secure_lookup_operation_action,
)
from mobile_api.helpers.mobile_execution_guard import mobile_execution_guard
from mobile_api.services.driver_dashboard_current_job import (
    fetch_active_movement,
    project_latest_action_summary,
)
from mobile_api.services.driver_job_allowed_actions_service import (
    DriverJobAllowedActionsService,
)
from tenant_workspace.models import TenantOperationAction


def _resolve_operation_action(
    action_id,
    *,
    ctx: SecureJobExecutionContext,
    request=None,
) -> TenantOperationAction | None:
    return secure_lookup_operation_action(
        action_id,
        ctx=ctx,
        request=request,
    )


def _driver_created_by_label(driver) -> str:
    name = (
        (getattr(driver, 'english_name', None) or '').strip()
        or (getattr(driver, 'arabic_name', None) or '').strip()
        or (getattr(driver, 'driver_code', None) or '').strip()
    )
    return name[:200]


def _parse_log_date(validated_body: dict, request=None):
    log_date = validated_body.get('log_date')
    if log_date is None and request is not None:
        data = getattr(request, 'data', None) or {}
        if hasattr(data, 'get'):
            raw = (data.get('log_date') or '').strip()
            if raw:
                log_date = parse_datetime(raw)
    if log_date is not None and timezone.is_naive(log_date):
        log_date = timezone.make_aware(log_date, timezone.get_current_timezone())
    return log_date or timezone.now()


class DriverJobExecuteService:
    @classmethod
    def _build_workflow_refresh(
        cls,
        *,
        driver,
        shipment,
        movement,
        action_log,
        request=None,
    ) -> dict[str, Any]:
        booking, shipment, movement, booking_item_type = (
            DriverJobAllowedActionsService._resolve_linkage(
                shipment=shipment,
                movement=movement,
            )
        )
        job_type = 'shipment' if shipment is not None else 'movement'
        job_id = str(shipment.shipment_id) if shipment else str(movement.movement_id)
        job_no = shipment.shipment_no if shipment else movement.movement_no

        invalidate_allowed_actions_cache(request)
        allowed = get_allowed_driver_actions_cached(
            request,
            driver=driver,
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
            job_type=job_type,
            job_id=job_id,
            job_no=job_no,
        )
        log_rows = load_scoped_action_logs(
            shipment=shipment,
            movement=movement,
            driver_id=driver.pk,
            limit=job_detail_log_scan_limit(),
        )
        if shipment is not None:
            execution_state = reconcile_shipment_state_from_logs(
                shipment,
                movement=movement,
                driver_id=driver.pk,
                log_rows=log_rows,
                request=request,
            )
        else:
            execution_state = reconcile_movement_state_from_logs(
                movement,
                driver_id=driver.pk,
                log_rows=log_rows,
                request=request,
            )
        latest = project_latest_action_summary(action_log, request)
        stage = (
            execution_state.get('operational_stage')
            or (shipment.shipment_status if shipment else None)
            or (movement.status if movement else None)
            or ''
        )
        return {
            'allowed_actions': allowed,
            'execution_state': execution_state,
            'latest_action': latest,
            'shipment_status': shipment.shipment_status if shipment else None,
            'movement_status': movement.status if movement else None,
            'operational_stage': stage,
        }

    @classmethod
    def _execute_core(
        cls,
        *,
        execution_ctx: SecureJobExecutionContext,
        driver,
        tenant_user,
        operation_action,
        shipment,
        movement,
        validated_body: dict,
        request=None,
    ) -> dict[str, Any]:
        with execution_transaction_timer(
            operation='execute_core',
            tenant_schema=str(execution_ctx.tenant_schema or '')[:64],
            driver_id=str(execution_ctx.driver_id or getattr(driver, 'driver_id', driver.pk)),
        ) as txn_metrics:
            return cls._execute_core_locked(
                execution_ctx=execution_ctx,
                driver=driver,
                tenant_user=tenant_user,
                operation_action=operation_action,
                shipment=shipment,
                movement=movement,
                validated_body=validated_body,
                request=request,
                txn_metrics=txn_metrics,
            )

    @classmethod
    def _execute_core_locked(
        cls,
        *,
        execution_ctx: SecureJobExecutionContext,
        driver,
        tenant_user,
        operation_action,
        shipment,
        movement,
        validated_body: dict,
        request=None,
        txn_metrics: dict | None = None,
    ) -> dict[str, Any]:
        shipment, movement = lock_entities_for_execution(
            shipment=shipment,
            movement=movement,
        )
        try:
            payload = validate_mobile_execution_payload(
                operation_action=operation_action,
                request=request,
                shipment=shipment,
            )
        except ValidationError as exc:
            return {
                'success': False,
                'code': 'execution_validation_failed',
                'error': '; '.join(getattr(exc, 'messages', []) or [str(exc)]),
            }

        booking, shipment, movement, booking_item_type = (
            DriverJobAllowedActionsService._resolve_linkage(
                shipment=shipment,
                movement=movement,
            )
        )

        ctx_err = require_execution_context(
            execution_ctx,
            driver=driver,
            tenant_user=tenant_user,
            request=request,
        )
        if ctx_err is not None:
            return ctx_err

        try:
            with mobile_execution_guard(execution_ctx):
                exec_result = ActionExecutionService.execute_driver_action(
                    operation_action=operation_action,
                    log_date=_parse_log_date(validated_body, request),
                    booking=booking,
                    shipment=shipment,
                    movement=movement,
                    truck=(
                        (shipment.truck if shipment else None)
                        or (movement.truck if movement else None)
                    ),
                    driver=driver,
                    tenant_user=tenant_user,
                    created_by_label=_driver_created_by_label(driver),
                    notes=payload['notes'],
                    source='Mobile',
                    source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                    source_ref=validated_body.get('source_ref') or '',
                    idempotency_key=validated_body.get('idempotency_key') or '',
                    booking_item_type=booking_item_type,
                    latitude=payload['latitude'],
                    longitude=payload['longitude'],
                    map_link=payload['map_link'],
                    mobile_cod_amount=payload.get('cod_amount'),
                )
        except ValidationError as exc:
            return {
                'success': False,
                'code': 'action_not_allowed',
                'error': '; '.join(getattr(exc, 'messages', []) or [str(exc)]),
            }

        action_log = exec_result.action_log
        media_count = 0
        if not exec_result.reused_existing:
            media_count = save_action_log_media_from_mobile_request(action_log, request)

        if shipment is not None:
            shipment.refresh_from_db()
        if movement is not None:
            movement.refresh_from_db()

        action = action_log.operation_action
        label = ''
        if action is not None:
            label = get_localized_value(
                request,
                action.english_label or action.action_code or '',
                action.arabic_label or '',
            )

        workflow = cls._build_workflow_refresh(
            driver=driver,
            shipment=shipment,
            movement=movement,
            action_log=action_log,
            request=request,
        )

        if txn_metrics is not None:
            txn_metrics['reused_existing'] = exec_result.reused_existing

        drift = bool((workflow.get('execution_state') or {}).get('has_drift'))
        record_execution_outcome(
            operation='execute_core',
            tenant_schema=str(getattr(tenant_user, 'tenant_schema', '') or '')[:64],
            driver_id=str(getattr(driver, 'driver_id', driver.pk)),
            reused_existing=exec_result.reused_existing,
            drift_detected=drift,
            txn_ms=txn_metrics.get('transaction_ms') if txn_metrics else None,
        )

        return {
            'success': True,
            'execution': {
                'log_id': str(action_log.log_id),
                'log_no': action_log.log_no,
                'log_date': action_log.log_date.isoformat() if action_log.log_date else None,
                'action_code': action.action_code if action else None,
                'action_label': label or None,
                'reused_existing': exec_result.reused_existing,
                'source_channel': action_log.source_channel or SOURCE_CHANNEL_MOBILE_DRIVER,
                'media_saved_count': media_count,
            },
            'workflow': workflow,
        }

    @classmethod
    def _authorize_before_execute(
        cls,
        *,
        ctx: SecureJobExecutionContext,
        operation_action,
        shipment,
        movement,
        validated_body: dict,
        request=None,
    ) -> dict[str, Any] | None:
        ctx_err = require_execution_context(
            ctx,
            driver=getattr(ctx, 'driver', None),
            request=request,
        )
        if ctx_err is not None:
            return ctx_err

        auth = authorize_driver_action_execution(
            operation_action,
            ctx=ctx,
            shipment=shipment,
            movement=movement,
            request=request,
            client_action_id=validated_body.get('action_id'),
        )
        if not auth.get('success'):
            return auth
        return None

    @classmethod
    @transaction.atomic
    def execute_shipment_action(
        cls,
        *,
        driver,
        tenant_user,
        shipment_id: str,
        validated_body: dict,
        request=None,
        execution_ctx: SecureJobExecutionContext,
    ) -> dict[str, Any]:
        ctx_err = require_execution_context(
            execution_ctx,
            driver=driver,
            tenant_user=tenant_user,
            request=request,
        )
        if ctx_err is not None:
            return ctx_err

        shipment = secure_load_shipment_for_execution(
            execution_ctx,
            shipment_id,
            request=request,
        )

        if shipment is None:
            return {
                'success': False,
                'code': 'job_not_found',
                'error': _('mobile.jobs.detail.shipment_not_found'),
            }

        operation_action = _resolve_operation_action(
            validated_body['action_id'],
            ctx=execution_ctx,
            request=request,
        )
        if operation_action is None:
            return {
                'success': False,
                'code': 'invalid_action',
                'error': _('mobile.jobs.execute.invalid_action'),
            }

        movement = fetch_active_movement(driver=driver, shipment=shipment)
        denied = cls._authorize_before_execute(
            ctx=execution_ctx,
            operation_action=operation_action,
            shipment=shipment,
            movement=movement,
            validated_body=validated_body,
            request=request,
        )
        if denied is not None:
            return denied

        return cls._execute_core(
            execution_ctx=execution_ctx,
            driver=driver,
            tenant_user=tenant_user,
            operation_action=operation_action,
            shipment=shipment,
            movement=movement,
            validated_body=validated_body,
            request=request,
        )

    @classmethod
    @transaction.atomic
    def execute_movement_action(
        cls,
        *,
        driver,
        tenant_user,
        movement_id: str,
        validated_body: dict,
        request=None,
        execution_ctx: SecureJobExecutionContext,
    ) -> dict[str, Any]:
        ctx_err = require_execution_context(
            execution_ctx,
            driver=driver,
            tenant_user=tenant_user,
            request=request,
        )
        if ctx_err is not None:
            return ctx_err

        movement = secure_load_movement_for_execution(
            execution_ctx,
            movement_id,
            request=request,
        )

        if movement is None:
            return {
                'success': False,
                'code': 'job_not_found',
                'error': _('mobile.jobs.detail.movement_not_found'),
            }

        operation_action = _resolve_operation_action(
            validated_body['action_id'],
            ctx=execution_ctx,
            request=request,
        )
        if operation_action is None:
            return {
                'success': False,
                'code': 'invalid_action',
                'error': _('mobile.jobs.execute.invalid_action'),
            }

        shipment = getattr(movement, 'shipment', None)
        if shipment is not None:
            shipment = secure_load_shipment_for_execution(
                execution_ctx,
                str(shipment.shipment_id),
                request=request,
            )

        denied = cls._authorize_before_execute(
            ctx=execution_ctx,
            operation_action=operation_action,
            shipment=shipment,
            movement=movement,
            validated_body=validated_body,
            request=request,
        )
        if denied is not None:
            return denied

        return cls._execute_core(
            execution_ctx=execution_ctx,
            driver=driver,
            tenant_user=tenant_user,
            operation_action=operation_action,
            shipment=shipment,
            movement=movement,
            validated_body=validated_body,
            request=request,
        )
