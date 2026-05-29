"""
mobile_api/history/services/history_service.py

Orchestration for driver History list, filter preview, and detail.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from mobile_api.history.constants import HISTORY_ACTION_LOG_SCAN_LIMIT
from mobile_api.history.exceptions import HistoryError
from mobile_api.history.projections.history_card_projection import build_history_card
from mobile_api.history.projections.history_detail_projection import build_history_detail
from mobile_api.history.selectors.history_query import (
    HistoryListFilters,
    HistoryListPage,
    HistoryQuerySelector,
)
from mobile_api.job_detail.guards.entity_lookup import lookup_shipment_by_reference
from mobile_api.job_detail.guards.ownership import (
    assert_driver_active,
    driver_owns_shipment_leg,
)
from mobile_api.list_pagination import (
    ListPaginationParams,
    empty_pagination_page,
    paginate_sequence,
)
from iroad_tenants.services.timeline_query import (
    base_action_log_queryset,
    shipment_action_log_scope_q,
)
from tenant_workspace.models import TenantShipment


def parse_history_date(raw: str | None) -> date | None:
    """
    Parse filter date from query string.

    Accepts ISO ``YYYY-MM-DD`` and UI ``DD-MM-YYYY``.
    """
    token = (raw or '').strip()
    if not token:
        return None

    parsed = parse_date(token)
    if parsed is not None:
        return parsed

    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue

    raise HistoryError(
        str(_('mobile.history.invalid_date')),
        code='invalid_date',
        http_status=400,
        message_key='mobile.history.invalid_date',
    )


def validate_shipment_no(raw: str | None) -> str:
    token = (raw or '').strip()
    if len(token) > 64:
        raise HistoryError(
            str(_('mobile.history.shipment_no_too_long')),
            code='validation_failed',
            http_status=400,
            message_key='mobile.validation.failed',
        )
    return token


class HistoryService:
    """Driver history read APIs."""

    def __init__(self, *, selector: HistoryQuerySelector | None = None) -> None:
        self._selector = selector or HistoryQuerySelector()

    def list_history(
        self,
        driver: Any,
        *,
        tenant_schema: str,
        shipment_no: str = '',
        job_date: str | None = None,
        count_only: bool = False,
        pagination: ListPaginationParams | None = None,
        request: Any | None = None,
    ) -> HistoryListPage:
        schema = (tenant_schema or '').strip()
        if not schema:
            raise HistoryError(
                str(_('mobile.auth.tenant_required')),
                code='tenant_required',
                http_status=400,
                message_key='mobile.auth.tenant_required',
            )

        driver_err = assert_driver_active(driver)
        if driver_err:
            raise HistoryError(
                str(_('mobile.auth.driver_inactive')),
                code=driver_err,
                http_status=403,
                message_key='mobile.auth.driver_inactive',
            )

        filters = HistoryListFilters(
            shipment_no=validate_shipment_no(shipment_no),
            job_date=parse_history_date(job_date) if job_date else None,
            count_only=bool(count_only),
        )
        page_params = pagination or ListPaginationParams(page=1, page_size=10)

        with schema_context(schema):
            owned = self._selector.filter_owned_terminal_shipments(driver, filters=filters)
            results_found = len(owned)

            if filters.count_only:
                shell = empty_pagination_page(
                    page=page_params.page,
                    page_size=page_params.page_size,
                )
                return HistoryListPage(
                    items=[],
                    count=0,
                    results_found=results_found,
                    total_records=results_found,
                    total_pages=(
                        (results_found + page_params.page_size - 1) // page_params.page_size
                        if results_found
                        else 0
                    ),
                    current_page=page_params.page,
                    page_size=page_params.page_size,
                )

            cards = []
            for shipment in owned:
                log_count = self._count_forward_actions(shipment)
                cards.append(
                    build_history_card(
                        shipment,
                        actions_fired_count=log_count,
                        request=request,
                    )
                )

            page = paginate_sequence(
                cards,
                page=page_params.page,
                page_size=page_params.page_size,
            )
            return HistoryListPage(
                items=page['items'],
                count=page['count'],
                results_found=results_found,
                total_records=page['total_records'],
                total_pages=page['total_pages'],
                current_page=page['current_page'],
                page_size=page['page_size'],
            )

    def get_history_detail(
        self,
        driver: Any,
        shipment_id: str,
        *,
        tenant_schema: str,
        request: Any | None = None,
    ) -> dict[str, Any]:
        schema = (tenant_schema or '').strip()
        if not schema:
            raise HistoryError(
                str(_('mobile.auth.tenant_required')),
                code='tenant_required',
                http_status=400,
                message_key='mobile.auth.tenant_required',
            )

        driver_err = assert_driver_active(driver)
        if driver_err:
            raise HistoryError(
                str(_('mobile.auth.driver_inactive')),
                code=driver_err,
                http_status=403,
                message_key='mobile.auth.driver_inactive',
            )

        reference = (shipment_id or '').strip()
        if not reference:
            raise HistoryError(
                str(_('mobile.validation.failed')),
                code='invalid_job_reference',
                http_status=400,
                message_key='mobile.validation.failed',
            )

        with schema_context(schema):
            shipment = lookup_shipment_by_reference(reference)
            if shipment is None:
                raise HistoryError(
                    str(_('mobile.jobs.not_found')),
                    code='job_not_found',
                    http_status=404,
                    message_key='mobile.jobs.not_found',
                )

            if not self._is_history_eligible(shipment):
                raise HistoryError(
                    str(_('mobile.history.not_completed')),
                    code='history_not_available',
                    http_status=400,
                    message_key='mobile.history.not_completed',
                )

            booking = getattr(shipment, 'booking', None)
            if not driver_owns_shipment_leg(driver, booking, shipment):
                raise HistoryError(
                    str(_('mobile.auth.forbidden')),
                    code='forbidden',
                    http_status=403,
                    message_key='mobile.auth.forbidden',
                )

            logs = self._load_action_logs(shipment)
            return build_history_detail(shipment, logs, request=request)

    @staticmethod
    def _is_history_eligible(shipment: Any) -> bool:
        status = str(getattr(shipment, 'shipment_status', '') or '').strip()
        return status in {
            TenantShipment.ShipmentStatus.CLOSED,
            TenantShipment.ShipmentStatus.CANCELLED,
        }

    @staticmethod
    def _shipment_action_logs_qs(shipment: Any):
        """Bounded Action Log scan for one shipment (direct + movement-linked)."""
        shipment_pk = getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', None)
        return (
            base_action_log_queryset(require_action=True)
            .filter(shipment_action_log_scope_q(shipment_pk))
            .select_related('operation_action', 'shipment', 'truck_movement')
        )

    @staticmethod
    def _load_action_logs(shipment: Any) -> list[Any]:
        qs = (
            HistoryService._shipment_action_logs_qs(shipment)
            .prefetch_related('media_rows')
            .order_by('log_date', 'created_at')
        )
        return list(qs[:HISTORY_ACTION_LOG_SCAN_LIMIT])

    @staticmethod
    def _count_forward_actions(shipment: Any) -> int:
        """Count non-admin forward Action Log rows for one terminal shipment."""
        qs = HistoryService._shipment_action_logs_qs(shipment)
        return sum(
            1
            for row in qs[:HISTORY_ACTION_LOG_SCAN_LIMIT]
            if getattr(row, 'operation_action', None) is not None
            and not getattr(getattr(row, 'operation_action', None), 'admin_only', False)
        )
