"""
AD-001: operational access to Address Master (tenant schema).

Booking, shipment, dropdowns, lookups, and APIs MUST use this module so that:

* only ``status=Active`` rows are visible or accepted;
* only addresses for the **current client account** are visible or accepted.

Do **not** use ``TenantAddressMaster.objects`` for operational selection or
validation — use :func:`get_active_addresses` and
:func:`resolve_active_address_for_client` (or the helpers below).

Address Master CRUD (list/create/edit, deactivate) correctly uses
``TenantAddressMaster.objects`` to include inactive rows where required.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable, Optional

from django.core.exceptions import ValidationError
from django.db.models import QuerySet

from tenant_workspace.models import TenantAddressMaster


def _coerce_uuid(value: Any) -> Optional[uuid.UUID]:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def get_active_addresses(
    client_account_id: Any,
    *,
    select_related_client: bool = True,
    order_by: Iterable[str] = ('display_name',),
) -> QuerySet[TenantAddressMaster]:
    """
    Queryset of addresses usable in operational flows for one client.

    Equivalent to filtering by ``client_account_id`` and
    ``status=TenantAddressMaster.Status.ACTIVE``.
    """
    cid = _coerce_uuid(client_account_id)
    if cid is None:
        return TenantAddressMaster.objects.none()
    qs = TenantAddressMaster.objects.filter(
        client_account_id=cid,
        status=TenantAddressMaster.Status.ACTIVE,
    )
    if select_related_client:
        qs = qs.select_related('client_account')
    return qs.order_by(*order_by)


def get_active_addresses_for_pickup(client_account_id: Any) -> QuerySet[TenantAddressMaster]:
    """Pickup-capable categories (pickup-only or both)."""
    ac = TenantAddressMaster.AddressCategory
    return get_active_addresses(client_account_id).filter(
        address_category__in=(ac.PICKUP_ADDRESS, ac.BOTH),
    )


def get_active_addresses_for_delivery(client_account_id: Any) -> QuerySet[TenantAddressMaster]:
    """Delivery-capable categories (delivery-only or both)."""
    ac = TenantAddressMaster.AddressCategory
    return get_active_addresses(client_account_id).filter(
        address_category__in=(ac.DELIVERY_ADDRESS, ac.BOTH),
    )


def resolve_active_address_for_client(
    address_id: Any,
    client_account_id: Any,
) -> Optional[TenantAddressMaster]:
    """
    Return the row only if it exists, is Active, and belongs to ``client_account_id``.

    Failures are indistinguishable (``None``) to avoid cross-client address probing.
    """
    aid = _coerce_uuid(address_id)
    cid = _coerce_uuid(client_account_id)
    if aid is None or cid is None:
        return None
    return (
        TenantAddressMaster.objects.filter(
            pk=aid,
            client_account_id=cid,
            status=TenantAddressMaster.Status.ACTIVE,
        )
        .select_related('client_account')
        .first()
    )


def assert_active_address_for_client(address_id: Any, client_account_id: Any) -> TenantAddressMaster:
    """
    Like :func:`resolve_active_address_for_client` but raises ``ValueError`` on failure.
    """
    addr = resolve_active_address_for_client(address_id, client_account_id)
    if addr is None:
        raise ValueError(
            'Invalid or inaccessible address for this client (missing, inactive, or wrong client).'
        )
    return addr


def validate_active_address_for_client(
    address_id: Any,
    client_account_id: Any,
    *,
    field: str = 'address_id',
) -> TenantAddressMaster:
    """
    Form / API validation: raise ``ValidationError`` unless address is allowed.

    Use in ``clean_*``, serializers, and API handlers.
    """
    addr = resolve_active_address_for_client(address_id, client_account_id)
    if addr is None:
        raise ValidationError({
            field: ['Invalid or inactive address for this client.'],
        })
    return addr


def active_addresses_for_client(client_account_id: Any) -> QuerySet[TenantAddressMaster]:
    """Backward-compatible alias for :func:`get_active_addresses`."""
    return get_active_addresses(client_account_id)


__all__ = [
    'active_addresses_for_client',
    'assert_active_address_for_client',
    'get_active_addresses',
    'get_active_addresses_for_delivery',
    'get_active_addresses_for_pickup',
    'resolve_active_address_for_client',
    'validate_active_address_for_client',
]
