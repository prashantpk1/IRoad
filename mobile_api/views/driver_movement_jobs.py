"""
mobile_api/views/driver_movement_jobs.py

Driver movement job list APIs — separate operational queues (Phase 1).

Lightweight ``MovementJobCard`` projections with pagination (no timelines).
"""
from __future__ import annotations

from django.utils.translation import gettext as _

from mobile_api.serializers.driver_job_list import (
    MovementJobCardSerializer,
    MovementJobListMetaSerializer,
)
from mobile_api.services.driver_movement_list_service import (
    build_movement_job_card,
    list_driver_movements,
)
from mobile_api.views.driver_jobs import _DriverJobListBaseView


class _DriverMovementJobListBaseView(_DriverJobListBaseView):
    """Shared handler for movement operational queues."""

    job_list_entity_type = 'movement'
    locked_tab: str | None = None
    locked_queue: str = 'none'
    default_tab: str = 'active'
    list_message_key = 'mobile.jobs.movements_success'

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

        result = list_driver_movements(
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
                else 'movement_list_failed'
            )
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code=err_code,
                message_key='mobile.jobs.tab_all_not_allowed'
                if err_code == 'job_list_tab_all_not_allowed'
                else 'mobile.error.generic',
            )

        meta = dict(result['meta'])
        meta_serializer = MovementJobListMetaSerializer(data=meta)
        meta_serializer.is_valid(raise_exception=True)

        from mobile_api.helpers.job_list_filters import parse_movement_job_list_filters
        from mobile_api.helpers.job_list_ordering import parse_job_sort

        list_filters = parse_movement_job_list_filters(
            request,
            default_tab=self.default_tab,  # type: ignore[arg-type]
            locked_tab=locked_tab,
            locked_queue=locked_queue_typed,
        )
        return self._paginate_job_cards(
            request,
            queryset=result['queryset'],
            build_fn=build_movement_job_card,
            serializer_class=MovementJobCardSerializer,
            meta=meta_serializer.validated_data,
            message=_(self.list_message_key),
            message_key=self.list_message_key,
            driver=ctx.driver,
            entity_type='movement',
            include_actions=result.get('include_actions', True),
            list_ctx=ctx,
            list_filters=list_filters,
            sort=parse_job_sort(request),
        )


class DriverMovementJobListView(_DriverMovementJobListBaseView):
    """
    GET /api/v1/mobile/driver/jobs/movements/

    Query params: ``tab`` (active|completed|cancelled|all), ``queue`` (empty_move),
    ``q`` / ``search`` (movement_no / shipment_no), ``sort``, ``page``, ``page_size``,
    ``date_from``, ``date_to``, ``date_field`` (updated | operational).
    """

    locked_tab = None
    locked_queue = 'none'
    default_tab = 'active'
    list_message_key = 'mobile.jobs.movements_success'


class DriverMovementJobListActiveView(_DriverMovementJobListBaseView):
    """GET /api/v1/mobile/driver/jobs/movements/active/ — Scheduled / In Progress."""

    locked_tab = 'active'
    list_message_key = 'mobile.jobs.movements_active_success'


class DriverMovementJobListCompletedView(_DriverMovementJobListBaseView):
    """GET /api/v1/mobile/driver/jobs/movements/completed/"""

    locked_tab = 'completed'
    list_message_key = 'mobile.jobs.movements_completed_success'


class DriverMovementJobListCancelledView(_DriverMovementJobListBaseView):
    """GET /api/v1/mobile/driver/jobs/movements/cancelled/"""

    locked_tab = 'cancelled'
    list_message_key = 'mobile.jobs.movements_cancelled_success'


class DriverMovementJobListEmptyMoveView(_DriverMovementJobListBaseView):
    """
    GET /api/v1/mobile/driver/jobs/movements/empty/

    Empty truck moves among active movements (``queue=empty_move`` locked).
    """

    locked_tab = 'active'
    locked_queue = 'empty_move'
    list_message_key = 'mobile.jobs.movements_empty_success'
