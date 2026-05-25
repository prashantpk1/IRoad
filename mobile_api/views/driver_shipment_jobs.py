"""
mobile_api/views/driver_shipment_jobs.py

Driver shipment job list APIs — separate operational queues (Phase 1).

All endpoints return lightweight ``ShipmentJobCard`` projections with
``MobileApiPagination`` (no timelines, no portal detail serializers).
"""
from __future__ import annotations

from django.utils.translation import gettext as _

from mobile_api.serializers.driver_job_list import (
    ShipmentJobCardSerializer,
    ShipmentJobListMetaSerializer,
)
from mobile_api.services.driver_shipment_list_service import (
    build_shipment_job_card,
    list_driver_shipments,
)
from mobile_api.views.driver_jobs import _DriverJobListBaseView


class _DriverShipmentJobListBaseView(_DriverJobListBaseView):
    """
    Shared handler for shipment operational queues.

    Subclasses set ``locked_tab`` / ``locked_queue`` for path-based routes.
    """

    job_list_entity_type = 'shipment'
    locked_tab: str | None = None
    locked_queue: str = 'none'
    default_tab: str = 'active'
    list_message_key = 'mobile.jobs.shipments_success'

    def get(self, request):
        ctx, err = self._resolve_driver(request)
        if err is not None:
            return self.error(
                message=err.get('error', _('mobile.validation.failed')),
                code='job_list_context_failed',
                message_key='mobile.error.generic',
            )

        locked_tab = self.locked_tab  # type: ignore[arg-type]
        locked_queue = self.locked_queue if self.locked_queue != 'none' else None
        locked_queue_typed = locked_queue  # type: ignore[assignment]

        result = list_driver_shipments(
            driver=ctx.driver,
            tenant_schema=ctx.tenant_schema,
            request=request,
            default_tab=self.default_tab,  # type: ignore[arg-type]
            locked_tab=locked_tab,
            locked_queue=locked_queue_typed,
        )
        if not result.get('success'):
            err_code = (
                'job_list_tab_all_not_allowed'
                if result.get('code') == 'tab_all_not_allowed'
                else 'shipment_list_failed'
            )
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code=err_code,
                message_key='mobile.jobs.tab_all_not_allowed'
                if err_code == 'job_list_tab_all_not_allowed'
                else 'mobile.error.generic',
            )

        meta = dict(result['meta'])
        meta_serializer = ShipmentJobListMetaSerializer(data=meta)
        meta_serializer.is_valid(raise_exception=True)

        from mobile_api.helpers.job_list_filters import parse_shipment_job_list_filters
        from mobile_api.helpers.job_list_ordering import parse_job_sort

        list_filters = parse_shipment_job_list_filters(
            request,
            default_tab=self.default_tab,  # type: ignore[arg-type]
            locked_tab=locked_tab,
            locked_queue=locked_queue_typed,
        )
        return self._paginate_job_cards(
            request,
            queryset=result['queryset'],
            build_fn=build_shipment_job_card,
            serializer_class=ShipmentJobCardSerializer,
            meta=meta_serializer.validated_data,
            message=_(self.list_message_key),
            message_key=self.list_message_key,
            driver=ctx.driver,
            entity_type='shipment',
            include_actions=result.get('include_actions', True),
            list_ctx=ctx,
            list_filters=list_filters,
            sort=parse_job_sort(request),
        )


class DriverShipmentJobListView(_DriverShipmentJobListBaseView):
    """
    GET /api/v1/mobile/driver/jobs/shipments/

    General shipment queue. Default tab: ``active``.

    Query params:
      - ``tab``: active | completed | cancelled | all
      - ``queue``: none | pod_pending | cod_pending | delivery_pending | pickup_pending
      - ``q`` / ``search``: shipment_no or booking_no (icontains)
      - ``sort``: updated_desc (default), priority_desc, updated_asc, created_desc, number_*, status_asc
      - ``page``, ``page_size``
      - ``date_from``, ``date_to``, ``date_field`` (updated | operational)
    """

    locked_tab = None
    locked_queue = 'none'
    default_tab = 'active'
    list_message_key = 'mobile.jobs.shipments_success'


class DriverShipmentJobListActiveView(_DriverShipmentJobListBaseView):
    """GET /api/v1/mobile/driver/jobs/shipments/active/ — in-flight shipments."""

    locked_tab = 'active'
    list_message_key = 'mobile.jobs.shipments_active_success'


class DriverShipmentJobListCompletedView(_DriverShipmentJobListBaseView):
    """GET /api/v1/mobile/driver/jobs/shipments/completed/ — delivered/closed."""

    locked_tab = 'completed'
    list_message_key = 'mobile.jobs.shipments_completed_success'


class DriverShipmentJobListCancelledView(_DriverShipmentJobListBaseView):
    """GET /api/v1/mobile/driver/jobs/shipments/cancelled/ — cancelled shipments."""

    locked_tab = 'cancelled'
    list_message_key = 'mobile.jobs.shipments_cancelled_success'


class DriverShipmentJobListPodPendingView(_DriverShipmentJobListBaseView):
    """
    GET /api/v1/mobile/driver/jobs/shipments/pod-pending/

    Active shipments needing POD compliance (``queue=pod_pending`` locked).
    Optional ``q`` search still applies.
    """

    locked_tab = 'active'
    locked_queue = 'pod_pending'
    list_message_key = 'mobile.jobs.shipments_pod_pending_success'


class DriverShipmentJobListCodPendingView(_DriverShipmentJobListBaseView):
    """
    GET /api/v1/mobile/driver/jobs/shipments/cod-pending/

    Active COD shipments awaiting collection (``queue=cod_pending`` locked).
    """

    locked_tab = 'active'
    locked_queue = 'cod_pending'
    list_message_key = 'mobile.jobs.shipments_cod_pending_success'
