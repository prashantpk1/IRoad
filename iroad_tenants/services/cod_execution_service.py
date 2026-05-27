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

        should_post_treasury = True
        action_log_id = str(
            getattr(action_log, 'pk', None) or getattr(action_log, 'log_id', None) or ''
        ).strip()

        # Optional staged payment bundle integration (prep-only API).
        # Execute Action remains authority; this reads staging rows to:
        # - enforce variance rejection
        # - prevent bundle reuse across shipments/logs
        # - bind bundle ↔ action_log for legal audit
        try:
            from django.db import connection
            from mobile_api.payment_collection.models import PaymentCollectionBundle
            from iroad_tenants.services.treasury_side_effects import (
                consume_payment_collection_bundle_for_action9,
            )

            tenant_schema = getattr(connection, 'schema_name', '') or ''
            driver_id = str(
                getattr(shipment, 'driver_id', '')
                or getattr(action_log, 'driver_id', '')
                or ''
            ).strip()
            shipment_id = str(
                getattr(shipment, 'pk', '')
                or getattr(shipment, 'shipment_id', '')
                or ''
            ).strip()
            idempotency_key = str(getattr(action_log, 'idempotency_key', '') or '').strip()

            if tenant_schema and driver_id and shipment_id and idempotency_key:
                bundle = (
                    PaymentCollectionBundle.objects.filter(
                        tenant_schema=tenant_schema,
                        driver_id=driver_id,
                        client_payment_id=idempotency_key,
                    )
                    .order_by('-created_at')
                    .first()
                )
                if bundle is not None:
                    if bool(getattr(bundle, 'variance_detected', False)):
                        raise ValidationError(
                            'Payment variance detected; cannot execute COD collection.'
                        )
                    if (bundle.shipment_id or '').strip() != shipment_id:
                        raise ValidationError('Payment bundle does not match shipment.')
                    amount = getattr(bundle, 'amount', None) or amount
                    already_consumed_by_this_action_log = bool(
                        (getattr(bundle, 'promotion_action_log_id', '') or '').strip()
                        and action_log_id
                        and str(getattr(bundle, 'promotion_action_log_id', '')).strip()
                        == action_log_id
                    )
                    if not already_consumed_by_this_action_log:
                        consume_payment_collection_bundle_for_action9(
                            bundle=bundle,
                            action_log=action_log,
                        )
                    else:
                        should_post_treasury = False
        except Exception as exc:
            if isinstance(exc, ValidationError):
                raise

        shipment.collection_status = TenantShipment.CollectionStatus.COLLECTED
        shipment.save(update_fields=['collection_status', 'updated_at'])
        if should_post_treasury:
            post_cod_collection_for_action9(
                shipment=shipment,
                action_log=action_log,
                amount=amount,
            )
