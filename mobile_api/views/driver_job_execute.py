"""
mobile_api/views/driver_job_execute.py

POST execute-action — transactional Action Log + side effects + workflow refresh.
"""

from __future__ import annotations

from django.utils.translation import gettext as _

from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from mobile_api.serializers.driver_job_execute import (
    ExecuteActionResponseDataSerializer,
    ExecuteDriverActionSerializer,
)
from mobile_api.services.driver_job_execute_service import DriverJobExecuteService
from mobile_api.views.driver_job_execution_base import _DriverJobExecutionBaseView


class _DriverJobExecuteBaseView(_DriverJobExecutionBaseView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _respond_execution(self, result: dict, *, message_key: str):
        if not result.get('success'):
            code = result.get('code') or 'execute_failed'
            http_map = {
                'job_not_found': 404,
                'invalid_action': 400,
                'invalid_shipment_id': 400,
                'invalid_movement_id': 400,
                'action_not_allowed': 403,
                'execution_validation_failed': 400,
            }
            http = http_map.get(code, 400)
            msg_key = {
                'job_not_found': 'mobile.jobs.detail.not_found',
                'action_not_allowed': 'mobile.jobs.execute.not_allowed',
                'execution_validation_failed': 'mobile.jobs.execute.validation_failed',
            }.get(code, 'mobile.error.generic')
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code=code,
                message_key=msg_key,
                http_code=http,
            )

        payload = {
            'execution': result.get('execution') or {},
            'workflow': result.get('workflow') or {},
        }
        serializer = ExecuteActionResponseDataSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        exec_block = serializer.validated_data.get('execution') or {}
        return self.success(
            message=_('mobile.jobs.execute.success'),
            data=serializer.validated_data,
            message_key=message_key,
            meta_extra={
                'reused_existing': exec_block.get('reused_existing', False),
                'log_no': exec_block.get('log_no', ''),
                'workflow_source': 'operation_execution.get_allowed_actions',
            },
        )


class DriverShipmentExecuteActionView(_DriverJobExecuteBaseView):
    """
    POST /api/v1/mobile/driver/jobs/shipments/{shipment_id}/actions/execute/

    Body (JSON or multipart):
      - ``action_id`` (required)
      - ``idempotency_key`` / ``source_ref`` (recommended)
      - ``notes``, ``latitude``, ``longitude``, ``map_link``
      - ``cod_amount`` (COD / A9)
      - ``media`` JSON array or ``media_file`` uploads
    """

    def post(self, request, shipment_id):
        ctx, err = self._resolve_execution_context(request)
        if err is not None:
            return self._execution_context_error(err)

        serializer = ExecuteDriverActionSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        result = DriverJobExecuteService.execute_shipment_action(
            driver=ctx.driver,
            tenant_user=ctx.tenant_user,
            shipment_id=shipment_id,
            validated_body=serializer.validated_data,
            request=request,
            execution_ctx=ctx,
        )
        return self._respond_execution(
            result,
            message_key='mobile.jobs.execute.shipment_success',
        )


class DriverMovementExecuteActionView(_DriverJobExecuteBaseView):
    """
    POST /api/v1/mobile/driver/jobs/movements/{movement_id}/actions/execute/
    """

    def post(self, request, movement_id):
        ctx, err = self._resolve_execution_context(request)
        if err is not None:
            return self._execution_context_error(err)

        serializer = ExecuteDriverActionSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        result = DriverJobExecuteService.execute_movement_action(
            driver=ctx.driver,
            tenant_user=ctx.tenant_user,
            movement_id=movement_id,
            validated_body=serializer.validated_data,
            request=request,
            execution_ctx=ctx,
        )
        return self._respond_execution(
            result,
            message_key='mobile.jobs.execute.movement_success',
        )
