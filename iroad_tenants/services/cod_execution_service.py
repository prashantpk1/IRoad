"""COD collection gates and Action 9 treasury side effects."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from iroad_tenants.driver_treasury_ops import post_cod_collection_for_action9
from tenant_workspace.models import TenantShipment


class CODExecutionService:
    @staticmethod
    def validate_delivered_transition(shipment, new_status) -> None:
        if shipment is None or not new_status:
            return
        if new_status != TenantShipment.ShipmentStatus.DELIVERED:
            return
        if (shipment.order_type or '').upper() == 'COD':
            if shipment.collection_status != TenantShipment.CollectionStatus.COLLECTED:
                raise ValidationError(
                    'COD shipment cannot move to Delivered until payment is collected.'
                )

    @staticmethod
    def apply_collect_payment_side_effect(*, shipment, action_log, amount=None) -> None:
        """Action 9 — mark collected and post treasury (idempotent)."""
        if shipment is None:
            return
        if (shipment.order_type or '').upper() != 'COD':
            return
        shipment.collection_status = TenantShipment.CollectionStatus.COLLECTED
        shipment.save(update_fields=['collection_status', 'updated_at'])
        post_cod_collection_for_action9(
            shipment=shipment,
            action_log=action_log,
            amount=amount,
        )
