"""POD execution gates and action-log POD side effects."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from iroad_tenants.operation_runtime.pod_action import (
    apply_pod_posting_from_action_log,
    birth_pod_from_action_log,
)
from tenant_workspace.models import TenantShipment


class PODExecutionService:
    @staticmethod
    def validate_delivered_transition(shipment, new_status) -> None:
        if shipment is None or not new_status:
            return
        if new_status != TenantShipment.ShipmentStatus.DELIVERED:
            return
        compliant_statuses = {
            TenantShipment.PodStatus.COMPLIANT,
            TenantShipment.PodStatus.HARD_COPY_RECEIVED,
        }
        if (shipment.pod_status or '') not in compliant_statuses:
            raise ValidationError(
                'Shipment cannot move to Delivered until POD is compliant '
                '(all delivery-note documents verified).'
            )

    @staticmethod
    def birth_pod_from_action_log(action_log, *, created_by_label: str = ''):
        return birth_pod_from_action_log(
            action_log,
            created_by_label=created_by_label,
        )

    @staticmethod
    def apply_pod_posting_from_action_log(
        *,
        action_log,
        pod_document,
        shipment,
        created_by_label: str = '',
    ) -> None:
        apply_pod_posting_from_action_log(
            action_log=action_log,
            pod_document=pod_document,
            shipment=shipment,
            created_by_label=created_by_label,
        )
