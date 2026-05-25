"""
mobile_api/views/driver_job_detail.py

Job Detail snapshot APIs — lightweight execution screen payloads.
"""

from __future__ import annotations

from django.conf import settings
from django.utils.translation import gettext as _

from mobile_api.helpers.job_detail_guards import enforce_detail_payload_size
from mobile_api.helpers.job_detail_observability import job_detail_timer, maybe_record_query_count
from mobile_api.helpers.job_list_guards import job_list_strict_payload
from mobile_api.helpers.job_list_observability import estimate_payload_bytes, log_payload_size
from mobile_api.permissions import HasDriverJobsAccess
from mobile_api.serializers.driver_job_detail import JobDetailSnapshotSerializer
from mobile_api.services.driver_job_detail_service import DriverJobDetailService
from mobile_api.throttling import MobileJobListThrottle
from mobile_api.views.base import MobileAPIView
from mobile_api.views.driver_profile import (
    _mobile_tenant_schema,
    _mobile_user_id,
)
from mobile_api.helpers.job_list_security import resolve_secure_job_list_context


class _DriverJobDetailBaseView(MobileAPIView):
    permission_classes = [HasDriverJobsAccess]
    required_mobile_capability = 'mobile.driver.jobs'
    throttle_classes = [MobileJobListThrottle]

    def _resolve_driver(self, request):
        tenant_schema = _mobile_tenant_schema(request)
        secured = resolve_secure_job_list_context(
            user_id=_mobile_user_id(request),
            tenant_schema=tenant_schema,
            request=request,
        )
        if not secured.get('success'):
            return None, secured
        return secured['ctx'], None

    def _respond_snapshot(self, request, *, result: dict, message_key: str):
        if not result.get('success'):
            code = result.get('code') or 'job_detail_failed'
            http = 404 if code == 'job_not_found' else 400
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code=code,
                message_key='mobile.jobs.detail.not_found'
                if code == 'job_not_found'
                else 'mobile.error.generic',
                http_code=http,
            )

        snapshot = result.get('snapshot') or {}
        serializer = JobDetailSnapshotSerializer(data=snapshot)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        _payload, payload_err = enforce_detail_payload_size(
            {'snapshot': validated},
            operation='job_detail',
        )
        if payload_err:
            return self.error(
                message=_('mobile.jobs.payload_too_large'),
                code=payload_err,
                message_key='mobile.jobs.payload_too_large',
                http_code=413,
            )

        cap = int(getattr(settings, 'MOBILE_API_JOBS_MAX_RESPONSE_BYTES', 524288) or 524288)
        size = estimate_payload_bytes(validated)
        log_payload_size(
            operation=f"job_detail_{result.get('meta', {}).get('entity_type', 'detail')}",
            items=[validated],
        )
        if size > cap and job_list_strict_payload():
            return self.error(
                message=_('mobile.jobs.payload_too_large'),
                code='job_detail_payload_too_large',
                message_key='mobile.jobs.payload_too_large',
                http_code=413,
            )

        meta = dict(result.get('meta') or {})
        return self.success(
            message=_(message_key),
            data={'snapshot': validated},
            message_key=message_key,
            meta_extra=meta,
        )

    def _respond_allowed_actions(self, result: dict):
        from mobile_api.serializers.driver_job_allowed_actions import (
            AllowedActionsPayloadSerializer,
        )

        if not result.get('success'):
            code = result.get('code') or 'job_actions_failed'
            http = 404 if code == 'job_not_found' else 400
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code=code,
                message_key='mobile.jobs.actions.not_found'
                if code == 'job_not_found'
                else 'mobile.error.generic',
                http_code=http,
            )

        block = result.get('allowed_actions') or {}
        serializer = AllowedActionsPayloadSerializer(data=block)
        serializer.is_valid(raise_exception=True)
        return self.success(
            message=_('mobile.jobs.actions.success'),
            data={'allowed_actions': serializer.validated_data},
            message_key='mobile.jobs.actions.success',
            meta_extra={
                'workflow_source': 'operation_execution.get_allowed_actions',
                'action_count': serializer.validated_data.get('count', 0),
            },
        )


class DriverShipmentJobDetailView(_DriverJobDetailBaseView):
    """
    GET /api/v1/mobile/driver/jobs/shipments/{shipment_id}/

    Lightweight shipment execution snapshot (no portal serializers, no full timeline).

    Query params:
      - ``include_timeline=0`` — omit timeline preview (default: include, max 15 rows)
      - ``include_actions=0`` — omit allowed-actions engine call
    """

    def get(self, request, shipment_id):
        ctx, err = self._resolve_driver(request)
        if err is not None:
            return self.error(
                message=err.get('error', _('mobile.validation.failed')),
                code='job_detail_context_failed',
                message_key='mobile.error.generic',
            )

        with job_detail_timer(
            operation='job_detail_shipment',
            tenant_schema=ctx.tenant_schema,
            driver_id=ctx.driver_id,
        ) as metrics:
            result = DriverJobDetailService.get_shipment_job_detail(
                driver=ctx.driver,
                tenant_user=ctx.tenant_user,
                shipment_id=shipment_id,
                request=request,
            )
            maybe_record_query_count(metrics)
            if result.get('success'):
                meta = result.get('meta') or {}
                metrics['log_scan_count'] = meta.get('timeline_preview_limit', '')
            response = self._respond_snapshot(
                request,
                result=result,
                message_key='mobile.jobs.detail.shipment_success',
            )
        return response


class DriverMovementJobDetailView(_DriverJobDetailBaseView):
    """
    GET /api/v1/mobile/driver/jobs/movements/{movement_id}/

    Lightweight movement / empty-move execution snapshot.
    """

    def get(self, request, movement_id):
        ctx, err = self._resolve_driver(request)
        if err is not None:
            return self.error(
                message=err.get('error', _('mobile.validation.failed')),
                code='job_detail_context_failed',
                message_key='mobile.error.generic',
            )

        with job_detail_timer(
            operation='job_detail_movement',
            tenant_schema=ctx.tenant_schema,
            driver_id=ctx.driver_id,
        ) as metrics:
            result = DriverJobDetailService.get_movement_job_detail(
                driver=ctx.driver,
                tenant_user=ctx.tenant_user,
                movement_id=movement_id,
                request=request,
            )
            maybe_record_query_count(metrics)
            response = self._respond_snapshot(
                request,
                result=result,
                message_key='mobile.jobs.detail.movement_success',
            )
        return response
