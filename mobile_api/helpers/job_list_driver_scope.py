"""
mobile_api/helpers/job_list_driver_scope.py

Index-friendly driver shipment scope without OR joins on list query plans.

Uses PostgreSQL UNION of two indexed lookups (direct driver + booking assignment),
then filters the list queryset by ``pk IN (subquery)``.
"""
from __future__ import annotations

from django.conf import settings
from django.db.models import QuerySet, Subquery

from mobile_api.helpers.operational_status import driver_shipment_scope_q


def _driver_pk(driver):
    return getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)


def job_list_union_driver_scope_enabled() -> bool:
    return bool(getattr(settings, 'MOBILE_API_JOBS_UNION_DRIVER_SCOPE', True))


def driver_shipment_pk_union_subquery(driver):
    """
    UNION of shipment PKs: row ``driver_id`` and ``booking.assigned_driver_id``.

    Each branch can use ``tenant_shipment_driver_fk_idx`` /
    ``tenant_booking_assign_drv_idx`` independently.
    """
    from tenant_workspace.models import TenantShipment

    driver_id = _driver_pk(driver)
    if not driver_id:
        return TenantShipment.objects.none().values('pk')

    direct = TenantShipment.objects.filter(driver_id=driver_id).values('pk')
    via_booking = TenantShipment.objects.filter(
        booking__assigned_driver_id=driver_id,
    ).values('pk')
    return direct.union(via_booking, all=True)


def filter_shipments_for_driver(driver) -> QuerySet:
    """
    Shipments visible to the driver (operational correctness preserved).

    Falls back to legacy OR ``Q`` when ``MOBILE_API_JOBS_UNION_DRIVER_SCOPE`` is False.
    """
    from tenant_workspace.models import TenantShipment

    if not job_list_union_driver_scope_enabled():
        return TenantShipment.objects.filter(driver_shipment_scope_q(driver))

    return TenantShipment.objects.filter(
        pk__in=Subquery(driver_shipment_pk_union_subquery(driver)),
    )
