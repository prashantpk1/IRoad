"""
Mobile POD upload and COD collection — compliance gates + Action Log pipeline.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from mobile_api.helpers.compliance_operation_actions import (
    resolve_cod_collect_action,
    resolve_pod_upload_action,
)
from mobile_api.helpers.job_execution_security import (
    SecureJobExecutionContext,
    authorize_driver_action_execution,
    require_execution_context,
    secure_load_shipment_for_execution,
    strip_execution_audit_tamper_fields,
)
from mobile_api.helpers.pod_cod_validation import (
    validate_cod_collection_compliance,
    validate_pod_upload_compliance,
)
from mobile_api.services.driver_dashboard_current_job import (
    fetch_active_movement,
    project_cod_state,
    project_pod_state,
)
from mobile_api.services.driver_job_execute_service import DriverJobExecuteService
from tenant_workspace.models import (
    DriverTreasuryTransaction,
    TenantShipmentDocument,
)


def _parse_uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _compliance_pod_block(shipment, *, pod_document=None, request=None) -> dict[str, Any]:
    shipment.refresh_from_db()
    pod_state = project_pod_state(shipment=shipment)
    doc_block = None
    if pod_document is not None:
        doc_block = {
            'document_id': str(pod_document.pk),
            'record_no': pod_document.record_no,
            'status': pod_document.status,
            'document_type': pod_document.document_type,
        }
    elif shipment is not None:
        latest = (
            TenantShipmentDocument.objects.filter(
                shipment_id=shipment.pk,
                document_type='pod',
            )
            .order_by('-created_at')
            .first()
        )
        if latest is not None:
            doc_block = {
                'document_id': str(latest.pk),
                'record_no': latest.record_no,
                'status': latest.status,
                'document_type': latest.document_type,
            }
    return {
        'pod_status': pod_state.get('status') or '',
        'pod_type': getattr(shipment, 'pod_type', None) or pod_state.get('pod_type') or '',
        'needs_attention': pod_state.get('needs_attention', False),
        'is_pending': pod_state.get('is_pending', False),
        'shipment_status': shipment.shipment_status,
        'document': doc_block,
    }


def _compliance_cod_block(shipment, *, action_log=None) -> dict[str, Any]:
    shipment.refresh_from_db()
    cod_state = project_cod_state(shipment=shipment)
    treasury_block = {
        'posted': False,
        'transaction_no': None,
        'amount': None,
    }
    if action_log is not None:
        txn = (
            DriverTreasuryTransaction.objects.filter(
                operation_action_log_id=action_log.pk,
            )
            .order_by('-created_at')
            .first()
        )
        if txn is not None:
            treasury_block = {
                'posted': True,
                'transaction_no': txn.transaction_no,
                'amount': str(txn.amount),
            }
        elif cod_state.get('is_collection_pending') is False:
            treasury_block['posted'] = True
            treasury_block['amount'] = str(shipment.cod_amount or '')

    return {
        'order_type': cod_state.get('order_type') or '',
        'collection_status': cod_state.get('collection_status') or '',
        'cod_amount': str(shipment.cod_amount or cod_state.get('cod_amount') or ''),
        'is_cod_order': cod_state.get('is_cod_order', False),
        'is_collection_pending': cod_state.get('is_collection_pending', False),
        'shipment_status': shipment.shipment_status,
        'treasury': treasury_block,
    }


class DriverJobPodCodService:
    @classmethod
    def _normalize_body(cls, validated_body: dict, *, cod_amount: Decimal | None = None) -> dict:
        body = dict(validated_body)
        if cod_amount is not None:
            body['cod_amount'] = cod_amount
        return body

    @classmethod
    @transaction.atomic
    def upload_pod(
        cls,
        *,
        driver,
        tenant_user,
        shipment_id: str,
        validated_body: dict,
        request=None,
        execution_ctx: SecureJobExecutionContext,
    ) -> dict[str, Any]:
        validated_body = strip_execution_audit_tamper_fields(validated_body)
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

        operation_action = resolve_pod_upload_action()
        if operation_action is None:
            return {
                'success': False,
                'code': 'action_not_configured',
                'error': _('mobile.jobs.pod.action_not_configured'),
            }

        try:
            validate_pod_upload_compliance(
                shipment=shipment,
                driver=driver,
                operation_action=operation_action,
                request=request,
            )
        except ValidationError as exc:
            return {
                'success': False,
                'code': 'pod_validation_failed',
                'error': '; '.join(getattr(exc, 'messages', []) or [str(exc)]),
            }

        movement = fetch_active_movement(driver=driver, shipment=shipment)
        auth = authorize_driver_action_execution(
            operation_action,
            ctx=execution_ctx,
            shipment=shipment,
            movement=movement,
            request=request,
        )
        if not auth.get('success'):
            return auth

        result = DriverJobExecuteService._execute_core(
            execution_ctx=execution_ctx,
            driver=driver,
            tenant_user=tenant_user,
            operation_action=operation_action,
            shipment=shipment,
            movement=movement,
            validated_body=cls._normalize_body(validated_body),
            request=request,
        )
        if not result.get('success'):
            return result

        exec_block = result.get('execution') or {}
        pod_document = None
        if not exec_block.get('reused_existing'):
            pod_document = (
                TenantShipmentDocument.objects.filter(
                    shipment_id=shipment.pk,
                    document_type='pod',
                )
                .order_by('-created_at')
                .first()
            )

        return {
            'success': True,
            'operation': 'upload_pod',
            'execution': result.get('execution') or {},
            'workflow': result.get('workflow') or {},
            'compliance': {
                'pod': _compliance_pod_block(shipment, pod_document=pod_document, request=request),
            },
        }

    @classmethod
    @transaction.atomic
    def collect_cod(
        cls,
        *,
        driver,
        tenant_user,
        shipment_id: str,
        validated_body: dict,
        request=None,
        execution_ctx: SecureJobExecutionContext,
    ) -> dict[str, Any]:
        validated_body = strip_execution_audit_tamper_fields(validated_body)
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

        operation_action = resolve_cod_collect_action()
        if operation_action is None:
            return {
                'success': False,
                'code': 'action_not_configured',
                'error': _('mobile.jobs.cod.action_not_configured'),
            }

        try:
            cod_amount = validate_cod_collection_compliance(
                shipment=shipment,
                driver=driver,
                operation_action=operation_action,
                cod_amount_raw=validated_body.get('cod_amount'),
            )
        except ValidationError as exc:
            return {
                'success': False,
                'code': 'cod_validation_failed',
                'error': '; '.join(getattr(exc, 'messages', []) or [str(exc)]),
            }

        movement = fetch_active_movement(driver=driver, shipment=shipment)
        auth = authorize_driver_action_execution(
            operation_action,
            ctx=execution_ctx,
            shipment=shipment,
            movement=movement,
            request=request,
        )
        if not auth.get('success'):
            return auth

        body = cls._normalize_body(validated_body, cod_amount=cod_amount)
        result = DriverJobExecuteService._execute_core(
            execution_ctx=execution_ctx,
            driver=driver,
            tenant_user=tenant_user,
            operation_action=operation_action,
            shipment=shipment,
            movement=movement,
            validated_body=body,
            request=request,
        )
        if not result.get('success'):
            return result

        action_log = None
        log_id = (result.get('execution') or {}).get('log_id')
        if log_id:
            from tenant_workspace.models import TenantOperationActionLog

            action_log = TenantOperationActionLog.objects.filter(pk=log_id).first()

        return {
            'success': True,
            'operation': 'collect_cod',
            'execution': result.get('execution') or {},
            'workflow': result.get('workflow') or {},
            'compliance': {
                'cod': _compliance_cod_block(shipment, action_log=action_log),
            },
        }
