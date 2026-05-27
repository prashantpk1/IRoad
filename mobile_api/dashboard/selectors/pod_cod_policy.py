"""
mobile_api/dashboard/selectors/pod_cod_policy.py

Read-only POD/COD compliance flags for the driver dashboard.

Rules align with ``iroad_tenants.operation_runtime.latest_state`` (Delivered
gates) and portal POD helpers on ``TenantShipment`` column values — no duplicate
policy engine.
"""
from __future__ import annotations

from typing import Any

from tenant_workspace.models import TenantShipment

from iroad_tenants.driver_treasury_ops import (
    cod_client_collection_exists,
    ensure_active_driver_treasury,
)
from iroad_tenants.operation_runtime.latest_state import (
    validate_shipment_status_transition,
)
from mobile_api.hard_pod.models import HardPODCustodySubmission
from mobile_api.hard_pod.services.custody_authority_service import (
    HardPodCustodyAuthorityService,
)

# Mirror ``_tenant_shipment_pod_status_is_*`` in ``iroad_tenants.views``.
_POD_COMPLETE_STATUSES = frozenset(
    {
        TenantShipment.PodStatus.COMPLIANT,
        TenantShipment.PodStatus.HARD_COPY_RECEIVED,
    }
)
_POD_PENDING_STATUSES = frozenset(
    {
        TenantShipment.PodStatus.PENDING,
        TenantShipment.PodStatus.NOT_COMPLIANT,
    }
)
_TERMINAL_SHIPMENT_STATUSES = frozenset(
    {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.CANCELLED,
    }
)


def pod_status_is_complete(pod_status: str | None) -> bool:
    return (pod_status or '').strip() in _POD_COMPLETE_STATUSES


def pod_status_is_pending(pod_status: str | None) -> bool:
    return (pod_status or '').strip() in _POD_PENDING_STATUSES


def is_cod_shipment(shipment: Any | None) -> bool:
    if shipment is None:
        return False
    return (getattr(shipment, 'order_type', None) or '').strip().upper() == 'COD'


def derive_pod_pending(shipment: Any | None) -> bool:
    if shipment is None:
        return False
    return pod_status_is_pending(getattr(shipment, 'pod_status', None))


def derive_pod_compliant(shipment: Any | None) -> bool:
    if shipment is None:
        return False
    return pod_status_is_complete(getattr(shipment, 'pod_status', None))


def derive_hard_pod_pending(shipment: Any | None) -> bool:
    """Hard-copy POD type with delivery-note compliance still outstanding."""
    if shipment is None:
        return False
    pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()
    if pod_type != TenantShipment.PodType.HARD.casefold():
        return False
    if pod_status_is_complete(getattr(shipment, 'pod_status', None)):
        return False

    shipment_id = str(getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', '') or '').strip()
    driver = getattr(shipment, 'driver', None)
    driver_id = str(getattr(driver, 'pk', None) or getattr(shipment, 'driver_id', '') or '').strip()
    if not shipment_id:
        return True

    authority = HardPodCustodyAuthorityService().resolve_authority(
        tenant_schema=str(getattr(shipment, 'tenant_schema', '') or '').strip(),
        shipment_id=shipment_id,
        driver_id=driver_id,
    )
    if authority.get('custody_authority') in {
        'execute_action_log',
        'promoted_custody_submission',
    }:
        return False

    promoted_submission = HardPODCustodySubmission.objects.filter(
        shipment_id=shipment_id,
        driver_id=driver_id,
        promoted_at__isnull=False,
    ).exclude(
        promotion_action_log_id=''
    ).first()
    if promoted_submission is not None:
        return False
    return True


def derive_cod_pending(shipment: Any | None) -> bool:
    if shipment is None or not is_cod_shipment(shipment):
        return False
    return (
        getattr(shipment, 'collection_status', None)
        != TenantShipment.CollectionStatus.COLLECTED
    )


def derive_cod_collected(shipment: Any | None) -> bool:
    if shipment is None or not is_cod_shipment(shipment):
        return False
    return (
        getattr(shipment, 'collection_status', None)
        == TenantShipment.CollectionStatus.COLLECTED
    )


def derive_treasury_pending(
    shipment: Any | None,
    *,
    driver: Any | None = None,
) -> bool:
    """
    COD marked collected on the shipment but wallet Client Collection not posted.

    Uses ``cod_client_collection_exists`` from ``driver_treasury_ops`` (Action 9).
    """
    if shipment is None or not is_cod_shipment(shipment):
        return False
    if not derive_cod_collected(shipment):
        return False

    wallet_driver = driver or getattr(shipment, 'driver', None)
    if wallet_driver is None:
        return True

    treasury = ensure_active_driver_treasury(wallet_driver, auto_create=False)
    if treasury is None:
        return True

    return not cod_client_collection_exists(
        shipment=shipment,
        driver_treasury=treasury,
    )


def derive_delivery_blocked(shipment: Any | None) -> bool:
    """
    Whether Delivered transition would be blocked by POD/COD gates (doc §4.6).

    Delegates to ``validate_shipment_status_transition`` when possible; falls
    back to the same predicate without raising.
    """
    if shipment is None:
        return False
    status = (getattr(shipment, 'shipment_status', None) or '').strip()
    if status in _TERMINAL_SHIPMENT_STATUSES:
        return False

    try:
        validate_shipment_status_transition(
            shipment,
            TenantShipment.ShipmentStatus.DELIVERED,
        )
        return False
    except Exception:
        return True


def derive_pod_cod_flags(
    shipment: Any | None,
    *,
    driver: Any | None = None,
) -> dict[str, bool]:
    """All dashboard POD/COD booleans for one shipment."""
    return {
        'pod_pending': derive_pod_pending(shipment),
        'pod_compliant': derive_pod_compliant(shipment),
        'hard_pod_pending': derive_hard_pod_pending(shipment),
        'cod_pending': derive_cod_pending(shipment),
        'cod_collected': derive_cod_collected(shipment),
        'treasury_pending': derive_treasury_pending(shipment, driver=driver),
        'delivery_blocked': derive_delivery_blocked(shipment),
    }
