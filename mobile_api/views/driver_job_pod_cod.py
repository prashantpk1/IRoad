"""
mobile_api/views/driver_job_pod_cod.py

POD upload and COD collection — compliance-safe Action Log execution.
"""

from __future__ import annotations

from django.utils.translation import gettext as _

from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from mobile_api.helpers.job_execution_security import (
    request_may_collect_cod,
    request_may_upload_pod,
)
from mobile_api.serializers.driver_job_pod_cod import (
    CodCollectionResponseDataSerializer,
    CollectCodRequestSerializer,
    PodUploadResponseDataSerializer,
    UploadPodRequestSerializer,
)
from mobile_api.services.driver_job_pod_cod_service import DriverJobPodCodService
from mobile_api.views.driver_job_execution_base import _DriverJobExecutionBaseView


class _DriverJobPodCodBaseView(_DriverJobExecutionBaseView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _respond_pod_cod(self, result: dict, *, message_key: str, serializer_cls):
        if not result.get('success'):
            code = result.get('code') or 'compliance_failed'
            http_map = {
                'job_not_found': 404,
                'invalid_shipment_id': 400,
                'pod_validation_failed': 400,
                'cod_validation_failed': 400,
                'action_not_configured': 503,
                'action_not_allowed': 403,
                'execution_validation_failed': 400,
                'capability_denied': 403,
            }
            http = http_map.get(code, 400)
            msg_key = {
                'job_not_found': 'mobile.jobs.detail.not_found',
                'pod_validation_failed': 'mobile.jobs.pod.validation_failed',
                'cod_validation_failed': 'mobile.jobs.cod.validation_failed',
                'action_not_configured': 'mobile.jobs.compliance.action_not_configured',
                'action_not_allowed': 'mobile.jobs.execute.not_allowed',
                'execution_validation_failed': 'mobile.jobs.execute.validation_failed',
                'capability_denied': 'mobile.auth.jobs_execute_denied',
            }.get(code, 'mobile.error.generic')
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code=code,
                message_key=msg_key,
                http_code=http,
            )

        payload = {
            'operation': result.get('operation'),
            'execution': result.get('execution') or {},
            'workflow': result.get('workflow') or {},
            'compliance': result.get('compliance') or {},
        }
        serializer = serializer_cls(data=payload)
        serializer.is_valid(raise_exception=True)
        exec_block = serializer.validated_data.get('execution') or {}
        return self.success(
            message=_(message_key),
            data=serializer.validated_data,
            message_key=message_key,
            meta_extra={
                'operation': result.get('operation'),
                'reused_existing': exec_block.get('reused_existing', False),
                'log_no': exec_block.get('log_no', ''),
            },
        )


class DriverShipmentUploadPodView(_DriverJobPodCodBaseView):
    """
    POST /api/v1/mobile/driver/jobs/shipments/{shipment_id}/upload-pod/

    Resolves Action 7 / Upload POD, validates compliance, executes Action Log + POD side effects.
    Multipart: ``media_file`` (required), GPS, notes, idempotency fields.
    """

    def post(self, request, shipment_id):
        if not request_may_upload_pod(request):
            return self.error(
                message=_('mobile.auth.jobs_execute_denied'),
                code='capability_denied',
                message_key='mobile.auth.jobs_execute_denied',
                http_code=403,
            )

        ctx, err = self._resolve_execution_context(request)
        if err is not None:
            return self._execution_context_error(err)

        serializer = UploadPodRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        result = DriverJobPodCodService.upload_pod(
            driver=ctx.driver,
            tenant_user=ctx.tenant_user,
            shipment_id=shipment_id,
            validated_body=serializer.validated_data,
            request=request,
            execution_ctx=ctx,
        )
        return self._respond_pod_cod(
            result,
            message_key='mobile.jobs.pod.upload_success',
            serializer_cls=PodUploadResponseDataSerializer,
        )


class DriverShipmentCollectCodView(_DriverJobPodCodBaseView):
    """
    POST /api/v1/mobile/driver/jobs/shipments/{shipment_id}/collect-cod/

    Resolves Action 9 / Collect Payment, treasury posting, collection_status sync.
    """

    def post(self, request, shipment_id):
        if not request_may_collect_cod(request):
            return self.error(
                message=_('mobile.auth.jobs_execute_denied'),
                code='capability_denied',
                message_key='mobile.auth.jobs_execute_denied',
                http_code=403,
            )

        ctx, err = self._resolve_execution_context(request)
        if err is not None:
            return self._execution_context_error(err)

        serializer = CollectCodRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        result = DriverJobPodCodService.collect_cod(
            driver=ctx.driver,
            tenant_user=ctx.tenant_user,
            shipment_id=shipment_id,
            validated_body=serializer.validated_data,
            request=request,
            execution_ctx=ctx,
        )
        return self._respond_pod_cod(
            result,
            message_key='mobile.jobs.cod.collect_success',
            serializer_cls=CodCollectionResponseDataSerializer,
        )
