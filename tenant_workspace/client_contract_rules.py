"""Client contract period overlap and deletion guards (tenant schema)."""

from __future__ import annotations

from datetime import date

from django.db.models import Q

MSG_OVERLAPPING_CONTRACT = (
    'Another contract for this client overlaps the selected period. '
    'Adjust the start or end date so periods do not overlap.'
)
MSG_DELETE_BLOCKED_TRANSACTIONS = (
    'This contract cannot be deleted because bookings or shipments exist '
    'within its validity period.'
)


def date_ranges_overlap(
    start_a: date,
    end_a: date,
    start_b: date,
    end_b: date,
) -> bool:
    """True when two inclusive date ranges share at least one day."""
    return start_a <= end_b and start_b <= end_a


def find_overlapping_client_contract(
    *,
    client_account_id,
    start_date: date,
    end_date: date,
    exclude_contract_id=None,
):
    """Return the first overlapping ``TenantClientContract`` row, if any."""
    from tenant_workspace.models import TenantClientContract

    qs = TenantClientContract.objects.filter(
        client_account_id=client_account_id,
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    if exclude_contract_id:
        qs = qs.exclude(pk=exclude_contract_id)
    return qs.order_by('start_date').first()


def client_contract_overlap_field_errors(
    *,
    client_account_id,
    start_date: date | None,
    end_date: date | None,
    exclude_contract_id=None,
) -> dict[str, str]:
    """Return ``{field_name: message}`` when the period overlaps another contract."""
    if not client_account_id or not start_date or not end_date:
        return {}
    if end_date < start_date:
        return {}
    overlap = find_overlapping_client_contract(
        client_account_id=client_account_id,
        start_date=start_date,
        end_date=end_date,
        exclude_contract_id=exclude_contract_id,
    )
    if overlap is None:
        return {}
    return {
        'start_date': MSG_OVERLAPPING_CONTRACT,
        'end_date': MSG_OVERLAPPING_CONTRACT,
    }


def client_contract_has_period_transactions(contract) -> bool:
    """True when bookings or shipments for the client fall within the contract period."""
    from tenant_workspace.models import TenantBooking, TenantShipment

    if contract is None:
        return False
    start_date = contract.start_date
    end_date = contract.end_date
    client_account_id = contract.client_account_id
    if not client_account_id or not start_date or not end_date:
        return False

    booking_q = Q(
        client_account_id=client_account_id,
        booking_date__gte=start_date,
        booking_date__lte=end_date,
    ) & ~Q(booking_status=TenantBooking.Status.CANCELLED)
    if TenantBooking.objects.filter(booking_q).exists():
        return True

    execution_q = Q(
        client_account_id=client_account_id,
        execution_date__gte=start_date,
        execution_date__lte=end_date,
    ) & ~Q(booking_status=TenantBooking.Status.CANCELLED)
    if TenantBooking.objects.filter(execution_q).exists():
        return True

    shipment_q = Q(
        client_account_id=client_account_id,
        shipment_date__gte=start_date,
        shipment_date__lte=end_date,
    ) & ~Q(shipment_status=TenantShipment.ShipmentStatus.CANCELLED)
    return TenantShipment.objects.filter(shipment_q).exists()


def client_contract_delete_block_message(contract) -> str | None:
    """Return a user-facing block message when deletion is not allowed."""
    if client_contract_has_period_transactions(contract):
        return MSG_DELETE_BLOCKED_TRANSACTIONS
    return None
