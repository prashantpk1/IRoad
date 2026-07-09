"""Truck/driver operational eligibility queries (PCS §6.2.1)."""
from __future__ import annotations

import uuid

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
    'operation_driver_options_payload',
    'operation_truck_options_payload',
    'organization_profile_owner_fields',
    'truck_is_available_for_operations',
    'truck_operational_block_reason',
    'truck_operational_status_value',
]


def organization_profile_owner_fields() -> dict[str, str]:
    """Owner ID/Name from Organization Profile (PCS §6.1 / §6.2)."""
    profile = OrganizationProfile.objects.order_by('-updated_at', '-created_at').first()
    if profile is None:
        return {'owner_id': '', 'owner_name': ''}
    owner_id = (
        (profile.cr_number or '').strip()
        or (profile.tax_number or '').strip()
        or (profile.tenant_ref_no or '').strip()
    )
    owner_name = (
        (profile.name_en or '').strip()
        or (profile.name_ar or '').strip()
    )
    return {'owner_id': owner_id, 'owner_name': owner_name}


def _truck_option_row(truck) -> dict[str, str]:
    label = truck.truck_code
    if truck.plate_number:
        label = f'{truck.truck_code} - {truck.plate_number}'
    return {
        'truck_id': str(truck.pk),
        'truck_number': truck.truck_code,
        'label': label,
        'default_driver_id': (
            str(truck.default_driver_id_id) if truck.default_driver_id_id else ''
        ),
    }


def _driver_option_row(driver) -> dict[str, str]:
    display = driver.english_name or driver.arabic_name
    label = (
        f'{driver.driver_code} - {display}'
        if display
        else driver.driver_code
    )
    return {
        'driver_id': str(driver.pk),
        'username': driver.driver_code,
        'label': label,
    }


def operation_truck_options_payload(*, include_truck_ids=None) -> list[dict[str, str]]:
    """PCS §6.2.1 — only Active trucks with Available (or blank) operational status."""
    trucks = booking_eligible_trucks_queryset(include_truck_ids=include_truck_ids)
    return [_truck_option_row(truck) for truck in trucks[:500]]


def operation_driver_options_payload(*, include_driver_ids=None) -> list[dict[str, str]]:
    """PCS §6.2.1 — only Active drivers for operation/booking pickers."""
    drivers = booking_eligible_drivers_queryset(include_driver_ids=include_driver_ids)
    return [_driver_option_row(driver) for driver in drivers[:500]]


def _coerce_uuid(value):
    try:
        return uuid.UUID(str(value or '').strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _truck_include_primary_keys(include_truck_ids=None) -> list[uuid.UUID]:
    """Accept truck UUIDs or truck_code values (e.g. TR-0003) for include lists."""
    include_uuids: list[uuid.UUID] = []
    include_codes: list[str] = []
    for value in include_truck_ids or []:
        if not value:
            continue
        parsed = _coerce_uuid(value)
        if parsed is not None:
            include_uuids.append(parsed)
            continue
        code = str(value).strip()
        if code:
            include_codes.append(code)
    if include_codes:
        include_uuids.extend(
            TruckMaster.objects.filter(truck_code__in=include_codes).values_list(
                'pk',
                flat=True,
            )
        )
    return list(dict.fromkeys(include_uuids))


def _driver_include_primary_keys(include_driver_ids=None) -> list[uuid.UUID]:
    include_uuids: list[uuid.UUID] = []
    for value in include_driver_ids or []:
        if not value:
            continue
        parsed = _coerce_uuid(value)
        if parsed is not None:
            include_uuids.append(parsed)
    return list(dict.fromkeys(include_uuids))


def booking_eligible_trucks_queryset(*, include_truck_ids=None):
    qs = TruckMaster.active_objects.filter(
        Q(operational_status='') | Q(operational_status=TruckMaster.OperationalStatus.AVAILABLE)
    )
    include_ids = _truck_include_primary_keys(include_truck_ids)
    if include_ids:
        qs = TruckMaster.objects.filter(Q(pk__in=qs.values('pk')) | Q(pk__in=include_ids)).distinct()
    return qs.select_related('default_driver_id').order_by('truck_code')


def booking_eligible_drivers_queryset(*, include_driver_ids=None):
    qs = DriverMaster.active_objects.all()
    include_ids = _driver_include_primary_keys(include_driver_ids)
    if include_ids:
        qs = DriverMaster.objects.filter(Q(pk__in=qs.values('pk')) | Q(pk__in=include_ids)).distinct()
    return qs.order_by('driver_code')
