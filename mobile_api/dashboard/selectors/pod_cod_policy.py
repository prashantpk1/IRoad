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
        TenantShipment.PodStatus.COMPLETED,
    }
)
_POD_PENDING_STATUSES = frozenset(
    {
        TenantShipment.PodStatus.NOT_COMPLETED,
    }
)
_TERMINAL_SHIPMENT_STATUSES = frozenset(
    {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.CANCELLED,
    }
)
_HARD_POD_ACTIONABLE_STATUSES = frozenset(
    {
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
    }
)


def shipment_requires_hard_copy(shipment: Any | None) -> bool:
    """Booking- or shipment-level Hard Copy POD (not digital-only)."""
    if shipment is None:
        return False
    from iroad_tenants.operation_field_catalog import (
        normalize_operation_pod_type,
        operation_shipment_uses_hard_copy_pod,
    )

    if not operation_shipment_uses_hard_copy_pod(shipment):
        return False
    try:
        from iroad_tenants.operation_execution import _pending_hard_pod_custody_exists

        if _pending_hard_pod_custody_exists(shipment):
            return True
    except Exception:
        pass
    booking = getattr(shipment, 'booking', None)
    if booking is not None:
        booking_pod = normalize_operation_pod_type(
            getattr(booking, 'pod_type', None),
            default='',
        )
        if booking_pod == TenantShipment.PodType.HARD:
            return True
    pod_type = normalize_operation_pod_type(
        getattr(shipment, 'pod_type', None),
        default='',
    )
    return pod_type == TenantShipment.PodType.HARD


def hard_pod_stage_reached(
    shipment: Any | None,
    *,
    log_evidence: dict[str, bool] | None = None,
) -> bool:
    """
    Hard POD warnings/checklists apply during delivery/POD — and when a shipment was
    wrongly advanced to Delivered before hard-copy custody finished.
    """
    if shipment is None:
        return False
    status = (getattr(shipment, 'shipment_status', None) or '').strip()
    evidence = log_evidence or {}
    if status == TenantShipment.ShipmentStatus.DELIVERED:
        if evidence.get('hard_pod_log'):
            return False
        if evidence.get('pod_uploaded'):
            return True
        if pod_status_is_complete(getattr(shipment, 'pod_status', None)):
            return True
        try:
            from iroad_tenants.operation_execution import _pending_hard_pod_custody_exists

            if _pending_hard_pod_custody_exists(shipment):
                return True
        except Exception:
            pass
        return False
    if status in _TERMINAL_SHIPMENT_STATUSES:
        return False
    if status in _HARD_POD_ACTIONABLE_STATUSES:
        if status == TenantShipment.ShipmentStatus.AT_DELIVERY:
            try:
                from iroad_tenants.operation_runtime.shipment_execution_stage import (
                    shipment_unloading_completed_done,
                )

                if not shipment_unloading_completed_done(shipment):
                    if bool(evidence.get('pod_uploaded')):
                        return True
                    return False
            except Exception:
                pass
        return True
    return bool(evidence.get('pod_uploaded'))


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


def _resolve_tenant_schema(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
) -> str:
    schema = (tenant_schema or getattr(shipment, 'tenant_schema', '') or '').strip()
    if schema:
        return schema
    try:
        from django.db import connection

        return (getattr(connection, 'schema_name', None) or '').strip()
    except Exception:
        return ''


def _shipment_driver_id(
    shipment: Any | None,
    *,
    driver: Any | None = None,
) -> str:
    if driver is not None:
        resolved = str(getattr(driver, 'pk', None) or getattr(driver, 'driver_id', '') or '').strip()
        if resolved:
            return resolved
    if shipment is None:
        return ''
    ship_driver = getattr(shipment, 'driver', None)
    return str(
        getattr(ship_driver, 'pk', None)
        or getattr(shipment, 'driver_id', '')
        or ''
    ).strip()


def is_hard_pod_custody_complete(
    shipment: Any | None,
    *,
    log_evidence: dict[str, bool] | None = None,
    tenant_schema: str = '',
    driver: Any | None = None,
) -> bool:
    """
    Hard-copy custody is satisfied — Action Log ``hard_pod_log`` or promoted /
    linked custody submission (single source for workflow + hint + gates).
    """
    if shipment is None or not shipment_requires_hard_copy(shipment):
        return True
    evidence = dict(log_evidence or {})
    if evidence.get('hard_pod_log'):
        return True
    schema = _resolve_tenant_schema(shipment, tenant_schema=tenant_schema)
    shipment_id = str(
        getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', '') or ''
    ).strip()
    driver_id = _shipment_driver_id(shipment, driver=driver)
    if not shipment_id:
        return False
    try:
        from iroad_tenants.operation_execution import _pending_hard_pod_custody_exists

        if _pending_hard_pod_custody_exists(shipment):
            return False
    except Exception:
        pass
    try:
        authority = HardPodCustodyAuthorityService().resolve_authority(
            tenant_schema=schema,
            shipment_id=shipment_id,
            driver_id=driver_id,
        )
    except Exception:
        return False
    return authority.get('custody_authority') in {
        'execute_action_log',
        'promoted_custody_submission',
    }


def enrich_log_evidence_hard_pod(
    evidence: dict[str, bool] | None,
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    driver: Any | None = None,
    logs: list[Any] | None = None,
) -> dict[str, bool]:
    """Align ``hard_pod_log`` evidence with custody authority and hard-copy logs."""
    out = dict(evidence or {})
    if out.get('hard_pod_log') or shipment is None:
        return out
    if is_hard_pod_custody_complete(
        shipment,
        log_evidence=out,
        tenant_schema=tenant_schema,
        driver=driver,
    ):
        out['hard_pod_log'] = True
        return out
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        PodActionRole,
        classify_pod_action_role,
    )

    for log in logs or []:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        if classify_pod_action_role(action) == PodActionRole.HARD_POD:
            out['hard_pod_log'] = True
            break
        from iroad_tenants.operation_execution import (
            _is_standalone_hard_copy_collection_action,
        )

        if _is_standalone_hard_copy_collection_action(action):
            out['hard_pod_log'] = True
            break
    return out


def _resolve_log_evidence_for_shipment(
    shipment: Any | None,
    log_evidence: dict[str, bool] | None,
    *,
    tenant_schema: str = '',
    driver: Any | None = None,
    logs: list[Any] | None = None,
) -> dict[str, bool]:
    """Load Action Log evidence when callers omit it (status defer / repair paths)."""
    evidence = dict(log_evidence or {})
    if evidence or shipment is None:
        return evidence
    shipment_pk = getattr(shipment, 'pk', None)
    if not shipment_pk:
        return evidence
    try:
        from iroad_tenants.operation_runtime.side_effects import (
            _mobile_log_evidence_for_shipment,
        )

        evidence = _mobile_log_evidence_for_shipment(shipment)
        return enrich_log_evidence_hard_pod(
            evidence,
            shipment,
            tenant_schema=tenant_schema,
            driver=driver,
            logs=logs,
        )
    except Exception:
        return {}


def derive_hard_pod_pending(
    shipment: Any | None,
    *,
    log_evidence: dict[str, bool] | None = None,
    tenant_schema: str = '',
    driver: Any | None = None,
    logs: list[Any] | None = None,
) -> bool:
    """
    Hard-copy POD custody still outstanding for this shipment.

    Digital POD / DN verification (e.g. ``COMPLIANT``) do **not** clear hard-copy
    pending — only a standalone hard-copy Action Log or promoted custody submission.

    Hard-copy is **not** outstanding at Unloading Completed — only after digital
    POD (``pod_uploaded`` log evidence) or an in-flight custody submission.
    """
    if shipment is None:
        return False

    evidence = _resolve_log_evidence_for_shipment(
        shipment,
        log_evidence,
        tenant_schema=tenant_schema,
        driver=driver,
        logs=logs,
    )

    pod_type_hard = shipment_requires_hard_copy(shipment)
    if not pod_type_hard:
        try:
            from iroad_tenants.operation_execution import _pending_hard_pod_custody_exists

            if not _pending_hard_pod_custody_exists(shipment):
                return False
        except Exception:
            return False

    if not hard_pod_stage_reached(shipment, log_evidence=evidence):
        return False

    if is_hard_pod_custody_complete(
        shipment,
        log_evidence=evidence,
        tenant_schema=tenant_schema,
        driver=driver,
    ):
        return False

    if evidence.get('hard_pod_log'):
        return False
    if evidence.get('pod_uploaded'):
        return True
    try:
        from iroad_tenants.operation_execution import _pending_hard_pod_custody_exists

        if _pending_hard_pod_custody_exists(shipment):
            return True
    except Exception:
        pass
    try:
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            shipment_unloading_completed_done,
        )

        if not shipment_unloading_completed_done(shipment):
            return False
    except Exception:
        return False
    if derive_pod_compliant(shipment):
        return True
    return False


def derive_cod_pending(shipment: Any | None) -> bool:
    if shipment is None or not is_cod_shipment(shipment):
        return False
    if getattr(shipment, 'shipment_status', None) == TenantShipment.ShipmentStatus.CANCELLED:
        return False
    if getattr(shipment, 'collection_status', None) == TenantShipment.CollectionStatus.CANCELLED:
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
    if status not in {
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.DELIVERED,
    }:
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
    log_evidence: dict[str, bool] | None = None,
    tenant_schema: str = '',
) -> dict[str, bool]:
    """All dashboard POD/COD booleans for one shipment (columns + log evidence)."""
    evidence = dict(log_evidence or {})
    flags = {
        'pod_pending': derive_pod_pending(shipment),
        'pod_compliant': derive_pod_compliant(shipment),
        'hard_pod_pending': derive_hard_pod_pending(
            shipment,
            log_evidence=evidence,
            tenant_schema=tenant_schema,
        ),
        'cod_pending': derive_cod_pending(shipment),
        'cod_collected': derive_cod_collected(shipment),
        'treasury_pending': derive_treasury_pending(shipment, driver=driver),
        'delivery_blocked': derive_delivery_blocked(shipment),
    }

    if evidence.get('pod_uploaded'):
        flags['pod_pending'] = False
        if shipment_requires_hard_copy(shipment):
            custody_complete = is_hard_pod_custody_complete(
                shipment,
                log_evidence=evidence,
                tenant_schema=tenant_schema,
                driver=driver,
            )
            flags['hard_pod_pending'] = not custody_complete
            flags['pod_compliant'] = custody_complete and bool(
                evidence.get('pod_uploaded')
            )
        else:
            flags['pod_compliant'] = True
            flags['hard_pod_pending'] = False

    if shipment_requires_hard_copy(shipment) and is_hard_pod_custody_complete(
        shipment,
        log_evidence=evidence,
        tenant_schema=tenant_schema,
        driver=driver,
    ):
        flags['hard_pod_pending'] = False
        flags['pod_pending'] = False
        flags['pod_compliant'] = True

    if evidence.get('cod_collected_log') and is_cod_shipment(shipment):
        flags['cod_pending'] = False
        flags['cod_collected'] = True

    if flags.get('pod_compliant') and (
        not is_cod_shipment(shipment) or flags.get('cod_collected')
    ):
        flags['delivery_blocked'] = False

    return flags
