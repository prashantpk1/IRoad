"""Hybrid shipment status cache derived from action logs."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from iroad_tenants.operation_field_catalog import operation_pod_status_is_complete
from iroad_tenants.operation_runtime.impacts import (
    is_shipment_cancel_action,
    resolve_shipment_status_impact,
)
from iroad_tenants.operation_runtime.movement_ops import (
    auto_complete_loaded_movement_for_shipment,
)
from tenant_workspace.models import TenantOperationActionLog, TenantShipment


def _defer_pod_submitted_until_hard_copy_complete(shipment) -> bool:
    """Hard POD: POD Submitted only after digital + physical custody both complete."""
    if shipment is None:
        return False
    from iroad_tenants.operation_field_catalog import operation_shipment_uses_hard_copy_pod

    if not operation_shipment_uses_hard_copy_pod(shipment):
        return False
    evidence = {}
    shipment_pk = getattr(shipment, 'pk', None)
    try:
        from mobile_api.dashboard.selectors.pod_cod_policy import (
            derive_hard_pod_pending,
            enrich_log_evidence_hard_pod,
            is_hard_pod_custody_complete,
        )
        from iroad_tenants.operation_runtime.side_effects import (
            _mobile_log_evidence_for_shipment,
        )

        if shipment_pk:
            evidence = enrich_log_evidence_hard_pod(
                _mobile_log_evidence_for_shipment(shipment),
                shipment,
            )
        if is_hard_pod_custody_complete(shipment, log_evidence=evidence):
            return False
        return derive_hard_pod_pending(shipment, log_evidence=evidence)
    except Exception:
        return False


def clamp_shipment_status_cache_for_hard_pod(shipment, status: str | None) -> str | None:
    """Keep cache at At Delivery until hard-copy custody completes on Hard POD legs."""
    if not status or shipment is None:
        return status
    if status != TenantShipment.ShipmentStatus.POD_SUBMITTED:
        return status
    if _defer_pod_submitted_until_hard_copy_complete(shipment):
        return TenantShipment.ShipmentStatus.AT_DELIVERY
    return status


def resolve_effective_shipment_status_for_action(*, action, shipment=None):
    """
    Status column written when an action executes.

    Upload POD (``auto_pod_post``) must advance to POD Submitted, not Delivered.
    Credit shipments advance to Delivered on Unloading Completed (POD may still
    be pending). COD legs stay at At Delivery until POD + collection complete.
    End Job rows with booking Executed only still close the shipment.
    """
    from iroad_tenants.operation_runtime.workflow_action_policy import (
        action_is_job_close,
    )

    if action_is_job_close(action):
        return TenantShipment.ShipmentStatus.CLOSED
    if is_shipment_cancel_action(action):
        return TenantShipment.ShipmentStatus.CANCELLED
    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        is_unloading_completed_action,
    )

    if (
        shipment is not None
        and is_unloading_completed_action(action)
        and (getattr(shipment, 'order_type', None) or '').strip().upper() != 'COD'
    ):
        return TenantShipment.ShipmentStatus.DELIVERED
    raw = (getattr(action, 'shipment_status_impact', None) or '').strip()
    if not raw:
        return None
    new_status = resolve_shipment_status_impact(raw)
    if not new_status:
        return None
    if (
        new_status == TenantShipment.ShipmentStatus.DELIVERED
        and getattr(action, 'auto_pod_post', False)
    ):
        new_status = TenantShipment.ShipmentStatus.POD_SUBMITTED
    if new_status == TenantShipment.ShipmentStatus.POD_SUBMITTED:
        if _defer_pod_submitted_until_hard_copy_complete(shipment):
            return None
    return new_status


def validate_shipment_status_transition(shipment, new_status) -> None:
    """Doc §4.6 — gate Delivered on POD compliance and COD collection."""
    if shipment is None or not new_status:
        return
    if new_status != TenantShipment.ShipmentStatus.DELIVERED:
        return
    if (shipment.order_type or '').strip().upper() != 'COD':
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            shipment_unloading_completed_done,
        )

        if shipment_unloading_completed_done(shipment):
            return
    if not operation_pod_status_is_complete(shipment.pod_status):
        pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()
        hard_pod_deliverable = False
        if pod_type == TenantShipment.PodType.HARD.casefold():
            from iroad_tenants.operation_runtime.side_effects import (
                _mobile_log_evidence_for_shipment,
            )

            evidence = _mobile_log_evidence_for_shipment(shipment)
            hard_pod_deliverable = bool(evidence.get('hard_pod_log'))
        if not hard_pod_deliverable:
            raise ValidationError(
                'Shipment cannot move to Delivered until POD is compliant '
                '(all delivery-note documents verified).'
            )
    if shipment.order_type.upper() == 'COD':
        if shipment.collection_status != TenantShipment.CollectionStatus.COLLECTED:
            raise ValidationError(
                'COD shipment cannot move to Delivered until payment is collected.'
            )


def after_shipment_status_side_effects(shipment) -> None:
    if shipment is None:
        return
    if shipment.shipment_status in {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
    }:
        auto_complete_loaded_movement_for_shipment(shipment)
    from iroad_tenants.views import _tenant_shipment_document_refresh_shipment_pod

    _tenant_shipment_document_refresh_shipment_pod(shipment)
    if shipment.shipment_status in {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
    }:
        from iroad_tenants.operation_runtime.side_effects import (
            _sync_pod_status_from_mobile_logs,
            sync_booking_pod_status_from_shipments,
        )

        _sync_pod_status_from_mobile_logs(shipment)
        booking = getattr(shipment, 'booking', None)
        if booking is None and shipment.booking_id:
            from tenant_workspace.models import TenantBooking

            booking = TenantBooking.objects.filter(pk=shipment.booking_id).first()
        sync_booking_pod_status_from_shipments(booking)
        if booking is not None:
            from iroad_tenants.booking_status import sync_booking_status_after_item_change

            sync_booking_status_after_item_change(booking)


def derive_latest_action_status(shipment):
    if shipment is None:
        return None
    from iroad_tenants.operation_runtime.latest_action_aggregator import (
        shipment_status_rank,
    )
    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        infer_shipment_status_from_milestone_logs,
    )

    impact_status = None
    latest_logs = (
        TenantOperationActionLog.objects.filter(shipment_id=shipment.pk)
        .select_related('operation_action')
        .exclude(operation_action__isnull=True)
        .order_by('-log_date', '-created_at')[:50]
    )
    for log in latest_logs:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        derived = resolve_effective_shipment_status_for_action(
            action=action,
            shipment=shipment,
        )
        if derived:
            impact_status = derived
            break

    milestone_status = infer_shipment_status_from_milestone_logs(shipment)
    candidates = [s for s in (impact_status, milestone_status) if s]
    if not candidates:
        return None
    derived = max(candidates, key=shipment_status_rank)
    return clamp_shipment_status_cache_for_hard_pod(shipment, derived)


def repair_delivered_before_hard_pod_custody(shipment) -> bool:
    """
    Rewind Delivered / POD Submitted → At Delivery when digital POD is done
    but hard-copy custody is still outstanding.

    POD Submitted is applied only after both digital and hard-copy complete.
    """
    if shipment is None:
        return False
    current = (getattr(shipment, 'shipment_status', None) or '').strip()
    if current not in {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
    }:
        return False
    if not _shipment_needs_hard_pod_custody_repair(shipment):
        return False
    shipment.shipment_status = TenantShipment.ShipmentStatus.AT_DELIVERY
    shipment.save(update_fields=['shipment_status', 'updated_at'])
    return True


def _shipment_needs_hard_pod_custody_repair(shipment) -> bool:
    """True when Hard POD digital step is done but physical custody is not."""
    if shipment is None:
        return False
    from iroad_tenants.operation_field_catalog import operation_shipment_uses_hard_copy_pod

    if not operation_shipment_uses_hard_copy_pod(shipment):
        return False
    try:
        from iroad_tenants.operation_execution import _pending_hard_pod_custody_exists

        if _pending_hard_pod_custody_exists(shipment):
            return True
    except Exception:
        pass
    try:
        from mobile_api.dashboard.selectors.pod_cod_policy import (
            derive_hard_pod_pending,
            is_hard_pod_custody_complete,
        )
        from iroad_tenants.operation_runtime.side_effects import (
            _mobile_log_evidence_for_shipment,
        )

        evidence = _mobile_log_evidence_for_shipment(shipment)
        if is_hard_pod_custody_complete(shipment, log_evidence=evidence):
            return False
        return derive_hard_pod_pending(shipment, log_evidence=evidence)
    except Exception:
        return False


def repair_shipment_status_before_hard_pod_promotion(shipment) -> bool:
    """
    Repair legacy rows stuck at POD Submitted/Delivered before hard-copy confirm.

    Call immediately before Hard POD custody promotion execute.
    """
    repaired = repair_delivered_before_hard_pod_custody(shipment)
    if hasattr(shipment, 'refresh_from_db'):
        try:
            shipment.refresh_from_db(fields=['shipment_status', 'pod_status', 'updated_at'])
        except Exception:
            pass
    return repaired


def sync_shipment_status_from_action_log(shipment):
    """
    Gap 4 (hybrid): keep shipment_status column as cache, derive from latest action log.
    """
    if shipment is None:
        return shipment
    derived_status = derive_latest_action_status(shipment)
    derived_status = clamp_shipment_status_cache_for_hard_pod(shipment, derived_status)
    if not derived_status or shipment.shipment_status == derived_status:
        return shipment
    if (
        shipment.shipment_status == TenantShipment.ShipmentStatus.CANCELLED
        and derived_status != TenantShipment.ShipmentStatus.CANCELLED
    ):
        return shipment
    shipment.shipment_status = derived_status
    shipment.save(update_fields=['shipment_status', 'updated_at'])
    after_shipment_status_side_effects(shipment)
    return shipment


def apply_shipment_status_impact(*, shipment, action, created_by_label: str = '') -> None:
    """Apply shipment_status_impact with validation and follow-on effects."""
    if shipment is None or action is None:
        return
    new_status = resolve_effective_shipment_status_for_action(
        action=action,
        shipment=shipment,
    )
    if not new_status:
        return
    validate_shipment_status_transition(shipment, new_status)
    shipment.shipment_status = new_status
    shipment.save(update_fields=['shipment_status', 'updated_at'])
    after_shipment_status_side_effects(shipment)


def apply_hard_copy_pod_type_if_needed(*, shipment, action) -> None:
    if shipment is None or action is None:
        return
    if not action.hard_copy_collection:
        return
    from iroad_tenants.operation_field_catalog import operation_shipment_uses_hard_copy_pod

    if not operation_shipment_uses_hard_copy_pod(shipment):
        return
    shipment.pod_type = TenantShipment.PodType.HARD
    shipment.save(update_fields=['pod_type', 'updated_at'])


def apply_hard_copy_received_if_needed(*, shipment, action) -> None:
    """Mark physical hard-copy receipt after hard-copy collection execute."""
    if shipment is None or action is None:
        return
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    hard_copy_receipt = bool(getattr(action, 'hard_copy_collection', False))
    if not hard_copy_receipt and not is_pod_upload_action(action):
        return
    if (getattr(shipment, 'pod_type', None) or '').strip() != TenantShipment.PodType.HARD:
        return
    # Combined POD actions may execute hard custody before digital evidence.
    if getattr(action, 'auto_pod_post', False) or is_pod_upload_action(action):
        from iroad_tenants.operation_runtime.side_effects import (
            _mobile_log_evidence_for_shipment,
        )

        evidence = _mobile_log_evidence_for_shipment(shipment)
        if not evidence.get('pod_uploaded'):
            return
    shipment.pod_status = TenantShipment.PodStatus.COMPLETED
    shipment.save(update_fields=['pod_status', 'updated_at'])
