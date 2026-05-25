"""
mobile_api/views/driver_job_timeline.py

Cursor-paginated execution history for job detail screens.
"""

from __future__ import annotations

from django.utils.translation import gettext as _

from mobile_api.helpers.job_detail_observability import job_detail_timer, maybe_record_query_count
from mobile_api.serializers.driver_job_timeline import JobTimelineResponseDataSerializer
from mobile_api.services.driver_job_timeline_service import DriverJobTimelineService
from mobile_api.views.driver_job_detail import _DriverJobDetailBaseView


class _DriverJobTimelineBaseView(_DriverJobDetailBaseView):
    def _respond_timeline(self, result: dict, *, message_key: str):
        if not result.get('success'):
            code = result.get('code') or 'timeline_failed'
            http_map = {
                'job_not_found': 404,
                'invalid_shipment_id': 400,
                'invalid_movement_id': 400,
                'invalid_cursor': 400,
                'timeline_payload_too_large': 413,
            }
            http = http_map.get(code, 400)
            msg_key = {
                'job_not_found': 'mobile.jobs.detail.not_found',
                'invalid_cursor': 'mobile.jobs.timeline.invalid_cursor',
            }.get(code, 'mobile.error.generic')
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code=code,
                message_key=msg_key,
                http_code=http,
            )

        payload = {'timeline': result.get('timeline') or {}}
        serializer = JobTimelineResponseDataSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        block = serializer.validated_data.get('timeline') or {}
        pagination = block.get('pagination') or {}
        return self.success(
            message=_('mobile.jobs.timeline.success'),
            data=serializer.validated_data,
            message_key=message_key,
            meta_extra={
                'pagination_mode': 'cursor',
                'page_size': pagination.get('page_size', 0),
                'has_next': pagination.get('has_next', False),
                'item_count': pagination.get('count', 0),
            },
        )


class DriverShipmentTimelineView(_DriverJobTimelineBaseView):
    """
    GET /api/v1/mobile/driver/jobs/shipments/{shipment_id}/timeline/

    Query: ``page_size`` (default 20, max 50), ``cursor`` (opaque, no offset).
    """

    def get(self, request, shipment_id):
        ctx, err = self._resolve_driver(request)
        if err is not None:
            return self.error(
                message=err.get('error', _('mobile.validation.failed')),
                code='timeline_context_failed',
                message_key='mobile.error.generic',
            )

        with job_detail_timer(
            operation='timeline',
            tenant_schema=ctx.tenant_schema,
            driver_id=ctx.driver_id,
        ) as metrics:
            result = DriverJobTimelineService.get_shipment_timeline(
                driver=ctx.driver,
                shipment_id=shipment_id,
                request=request,
            )
            meta = result.get('meta') or {}
            metrics['item_count'] = meta.get('item_count', 0)
            metrics['media_batch_count'] = meta.get('media_batch_count', 0)
            maybe_record_query_count(metrics)
            response = self._respond_timeline(
                result,
                message_key='mobile.jobs.timeline.shipment_success',
            )
        return response


class DriverMovementTimelineView(_DriverJobTimelineBaseView):
    """
    GET /api/v1/mobile/driver/jobs/movements/{movement_id}/timeline/
    """

    def get(self, request, movement_id):
        ctx, err = self._resolve_driver(request)
        if err is not None:
            return self.error(
                message=err.get('error', _('mobile.validation.failed')),
                code='timeline_context_failed',
                message_key='mobile.error.generic',
            )

        with job_detail_timer(
            operation='timeline',
            tenant_schema=ctx.tenant_schema,
            driver_id=ctx.driver_id,
        ) as metrics:
            result = DriverJobTimelineService.get_movement_timeline(
                driver=ctx.driver,
                movement_id=movement_id,
                request=request,
            )
            meta = result.get('meta') or {}
            metrics['item_count'] = meta.get('item_count', 0)
            metrics['media_batch_count'] = meta.get('media_batch_count', 0)
            maybe_record_query_count(metrics)
            response = self._respond_timeline(
                result,
                message_key='mobile.jobs.timeline.movement_success',
            )
        return response
