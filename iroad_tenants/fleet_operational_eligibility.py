"""Truck/driver operational eligibility queries (PCS §6.2.1)."""
from __future__ import annotations

from django.db.models import Q

from iroad_tenants.fleet_operational_rules import (
    driver_is_available_for_operations,
    driver_operational_block_reason,
    truck_is_available_for_operations,
    truck_operational_block_reason,
    truck_operational_status_value,
)
from tenant_workspace.models import DriverMaster, OrganizationProfile, TruckMaster

__all__ = [
    'booking_eligible_drivers_queryset',
    'booking_eligible_trucks_queryset',
    'driver_is_available_for_operations',
    'driver_operational_block_reason',
    'organization_profile_owner_fields',
    'truck_is_available_for_operations',
    'truck_operational_block_reason',
    'truck_operational_status_value',
]


def organization_profile_owner_fields() -> dict[str, str]:
    """Owner ID/Name from Organization Profile (PCS §6.2)."""
    profile = OrganizationProfile.objects.order_by('-updated_at', '-created_at').first()
    if profile is None:
        return {'owner_id': '', 'owner_name': ''}
    owner_id = (
        (profile.cr_number or '').strip()
        or (profile.tenant_ref_no or '').strip()
        or (profile.tax_number or '').strip()
    )
    owner_name = (profile.name_en or '').strip() or (profile.name_ar or '').strip()
    return {'owner_id': owner_id, 'owner_name': owner_name}


def booking_eligible_trucks_queryset(*, include_truck_ids=None):
    qs = TruckMaster.active_objects.filter(
        Q(operational_status='') | Q(operational_status=TruckMaster.OperationalStatus.AVAILABLE)
    )
    include_ids = [pk for pk in (include_truck_ids or []) if pk]
    if include_ids:
        qs = TruckMaster.objects.filter(Q(pk__in=qs.values('pk')) | Q(pk__in=include_ids)).distinct()
    return qs.select_related('default_driver_id').order_by('truck_code')


def booking_eligible_drivers_queryset(*, include_driver_ids=None):
    qs = DriverMaster.active_objects.all()
    include_ids = [pk for pk in (include_driver_ids or []) if pk]
    if include_ids:
        qs = DriverMaster.objects.filter(Q(pk__in=qs.values('pk')) | Q(pk__in=include_ids)).distinct()
    return qs.order_by('driver_code')
