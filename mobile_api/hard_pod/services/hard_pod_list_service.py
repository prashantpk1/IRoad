"""
mobile_api/hard_pod/services/hard_pod_list_service.py

Read-only Hard POD pending queue for the authenticated driver.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Q
from django_tenants.utils import schema_context
from tenant_workspace.models import TenantShipment

from mobile_api.hard_pod.dto.hard_pod_response_builder import HardPodResponseBuilder
from mobile_api.hard_pod.services.hard_pod_projection_service import HardPodProjectionService
from mobile_api.job_detail.guards.ownership import assert_driver_active, driver_owns_shipment_leg, driver_pk


_TERMINAL_STATUSES = frozenset(
    {
        TenantShipment.ShipmentStatus.CANCELLED,
    }
)


class HardPodListService:
    """Driver Hard POD pending list — no workflow mutation."""

    def __init__(
        self,
        *,
        projection_service: HardPodProjectionService | None = None,
        response_builder: HardPodResponseBuilder | None = None,
    ) -> None:
        self._projection = projection_service or HardPodProjectionService()
        self._response = response_builder or HardPodResponseBuilder()

    def list_pending(
        self,
        *,
        driver: Any,
        tenant_schema: str,
    ) -> dict[str, Any]:
        schema = (tenant_schema or '').strip()
        driver_err = assert_driver_active(driver)
        if driver_err:
            return self._response.error_payload(
                code=driver_err,
                message_key=f'mobile.auth.{driver_err}',
            )

        if not schema:
            return self._response.error_payload(
                code='tenant_required',
                message_key='mobile.auth.tenant_required',
            )

        with schema_context(schema):
            shipments = self._query_driver_hard_pod_shipments(driver)
            rows = self._projection.build_rows_for_shipments(
                shipments,
                driver=driver,
                tenant_schema=schema,
                pending_only=True,
            )

        return self._response.list_pending(rows, tenant_schema=schema)

    def _query_driver_hard_pod_shipments(self, driver: Any) -> list[Any]:
        """Hard-POD shipments the driver may view (ownership enforced)."""
        pk = driver_pk(driver)
        if pk is None:
            return []

        qs = (
            TenantShipment.objects.filter(
                pod_type=TenantShipment.PodType.HARD,
            )
            .exclude(shipment_status__in=_TERMINAL_STATUSES)
            .filter(
                Q(driver_id=pk)
                | Q(booking__assigned_driver_id=pk)
                | Q(booking__booking_line_backload_driver_id=pk)
            )
            .select_related('booking')
            .distinct()
            .order_by('-updated_at', '-created_at')
        )

        return [
            shipment
            for shipment in qs
            if driver_owns_shipment_leg(driver, getattr(shipment, 'booking', None), shipment)
        ]
