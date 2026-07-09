"""POD upload must not advance COD shipments to Delivered before payment."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError

from iroad_tenants.operation_runtime.latest_state import (
    apply_shipment_status_impact,
    resolve_effective_shipment_status_for_action,
    validate_shipment_status_transition,
)
from tenant_workspace.models import TenantShipment


class PodSubmittedCodGateTests(TestCase):
    def test_resolve_effective_status_remaps_auto_pod_delivered_to_pod_submitted(self):
        action = SimpleNamespace(
            shipment_status_impact='Delivered',
            auto_pod_post=True,
        )
        self.assertEqual(
            resolve_effective_shipment_status_for_action(action=action),
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )

    def test_resolve_effective_status_credit_unloading_completed_to_delivered(self):
        action = SimpleNamespace(
            english_label='Unloading Completed',
            action_code='OA-0008',
            shipment_status_impact='At_Delivery',
            auto_pod_post=False,
        )
        shipment = SimpleNamespace(order_type='Credit')
        self.assertEqual(
            resolve_effective_shipment_status_for_action(
                action=action,
                shipment=shipment,
            ),
            TenantShipment.ShipmentStatus.DELIVERED,
        )

    def test_resolve_effective_status_cod_unloading_completed_stays_at_delivery(self):
        action = SimpleNamespace(
            english_label='Unloading Completed',
            action_code='OA-0008',
            shipment_status_impact='At_Delivery',
            auto_pod_post=False,
        )
        shipment = SimpleNamespace(order_type='COD')
        self.assertEqual(
            resolve_effective_shipment_status_for_action(
                action=action,
                shipment=shipment,
            ),
            TenantShipment.ShipmentStatus.AT_DELIVERY,
        )

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_completed_done',
        return_value=True,
    )
    def test_credit_delivered_allowed_after_unloading_without_pod(self, _mock_done):
        shipment = SimpleNamespace(
            order_type='Credit',
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        )
        validate_shipment_status_transition(
            shipment,
            TenantShipment.ShipmentStatus.DELIVERED,
        )

    def test_cod_shipment_rejects_delivered_until_payment(self):
        shipment = SimpleNamespace(
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.PENDING,
            pod_status=TenantShipment.PodStatus.COMPLETED,
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_shipment_status_transition(
                shipment,
                TenantShipment.ShipmentStatus.DELIVERED,
            )
        self.assertIn('payment is collected', str(ctx.exception))

    @patch(
        'iroad_tenants.operation_runtime.latest_state.after_shipment_status_side_effects',
    )
    def test_misconfigured_pod_action_applies_pod_submitted_for_cod(
        self,
        _mock_after,
    ):
        shipment = SimpleNamespace(
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.PENDING,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            save=lambda update_fields=None: None,
        )
        action = SimpleNamespace(
            shipment_status_impact='Delivered',
            auto_pod_post=True,
        )

        apply_shipment_status_impact(shipment=shipment, action=action)

        self.assertEqual(
            shipment.shipment_status,
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )


class HardPodDeferPodSubmittedTests(TestCase):
    @patch(
        'iroad_tenants.operation_runtime.latest_state._defer_pod_submitted_until_hard_copy_complete',
        return_value=True,
    )
    def test_digital_pod_deferred_until_hard_copy_on_hard_shipment(self, _defer):
        action = SimpleNamespace(
            shipment_status_impact='Delivered',
            auto_pod_post=True,
        )
        shipment = SimpleNamespace(
            order_type='COD',
            pod_type=TenantShipment.PodType.HARD,
        )
        self.assertIsNone(
            resolve_effective_shipment_status_for_action(
                action=action,
                shipment=shipment,
            ),
        )

    @patch(
        'iroad_tenants.operation_runtime.latest_state._defer_pod_submitted_until_hard_copy_complete',
        return_value=False,
    )
    def test_pod_submitted_when_hard_copy_complete(self, _defer):
        action = SimpleNamespace(
            shipment_status_impact='Delivered',
            auto_pod_post=True,
        )
        shipment = SimpleNamespace(
            order_type='COD',
            pod_type=TenantShipment.PodType.HARD,
        )
        self.assertEqual(
            resolve_effective_shipment_status_for_action(
                action=action,
                shipment=shipment,
            ),
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )


class PodSubmittedJobCloseTests(TestCase):
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': True, 'pod_uploaded': True},
    )
    @patch(
        'iroad_tenants.operation_execution._shipment_has_active_movement',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects.maybe_advance_delivered_when_job_close_ready',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_pod_compliance_satisfied',
        return_value=True,
    )
    @patch('iroad_tenants.operation_execution._executed_action_ids', return_value=set())
    @patch('iroad_tenants.operation_execution.get_allowed_actions')
    def test_end_job_allowed_after_cod_at_pod_submitted(
        self,
        mock_allowed,
        _exec_ids,
        _pod_ok,
        _advance,
        _movement,
        _mock_evidence,
    ):
        from iroad_tenants.operation_execution import validate_operation_action_allowed
        from uuid import uuid4

        mock_allowed.return_value = type(
            'QS',
            (),
            {'filter': lambda *a, **k: type('F', (), {'exists': lambda *a, **k: False})()},
        )()

        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_id=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.POD_SUBMITTED,
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.COLLECTED,
            pod_status=TenantShipment.PodStatus.COMPLETED,
            booking_id=uuid4(),
            booking_item_type='Outbound',
            pod_type='Digital',
        )
        booking = SimpleNamespace(
            pk=shipment.booking_id,
            booking_id=shipment.booking_id,
            trip_type='Round',
            assigned_driver_id=uuid4(),
            booking_line_backload_driver_id=uuid4(),
            shipments=SimpleNamespace(all=lambda: [shipment]),
        )
        shipment.booking = booking
        action = SimpleNamespace(
            pk=uuid4(),
            action_id=uuid4(),
            action_code='OA-0010',
            english_label='End Job',
            status='Active',
            shipment_status_impact=TenantShipment.ShipmentStatus.CLOSED,
            booking_status_impact='',
            movement_status_impact='',
            auto_pod_post=False,
            auto_movement_post=False,
            hard_copy_collection=False,
            auto_shipment_post=False,
            auto_treasury_post=False,
            condition_code='',
            sequence_number=10,
        )

        err = validate_operation_action_allowed(
            action,
            booking=booking,
            shipment=shipment,
        )
        self.assertIsNone(err)


class HardPodCustodyStatusAdvanceTests(TestCase):
    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_pod_compliance_satisfied',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._sync_pod_status_from_mobile_logs',
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects.sync_booking_pod_status_from_shipments',
    )
    @patch(
        'iroad_tenants.operation_runtime.latest_state.after_shipment_status_side_effects',
    )
    def test_cod_advances_to_pod_submitted_after_hard_pod(
        self,
        _after,
        _booking_sync,
        _sync_pod,
        _compliant,
        _hard_pending,
    ):
        from uuid import uuid4

        from iroad_tenants.operation_runtime.side_effects import (
            maybe_advance_shipment_after_hard_pod_custody,
        )

        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_id='ship-1',
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            order_type='COD',
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
            booking_id=None,
            booking=None,
            save=lambda update_fields=None: None,
            refresh_from_db=lambda fields=None: None,
        )
        self.assertTrue(
            maybe_advance_shipment_after_hard_pod_custody(shipment),
        )
        self.assertEqual(
            shipment.shipment_status,
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )
        self.assertEqual(
            shipment.pod_status,
            TenantShipment.PodStatus.COMPLETED,
        )

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_pod_compliance_satisfied',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._sync_pod_status_from_mobile_logs',
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects.sync_booking_pod_status_from_shipments',
    )
    @patch(
        'iroad_tenants.operation_runtime.latest_state.after_shipment_status_side_effects',
    )
    def test_credit_advances_to_pod_submitted_after_hard_pod(
        self,
        _after,
        _booking_sync,
        _sync_pod,
        _compliant,
        _hard_pending,
    ):
        from uuid import uuid4

        from iroad_tenants.operation_runtime.side_effects import (
            maybe_advance_shipment_after_hard_pod_custody,
        )

        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_id='ship-2',
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            order_type='Credit',
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
            booking_id=None,
            booking=None,
            save=lambda update_fields=None: None,
            refresh_from_db=lambda fields=None: None,
        )
        self.assertTrue(
            maybe_advance_shipment_after_hard_pod_custody(shipment),
        )
        self.assertEqual(
            shipment.shipment_status,
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )
        self.assertEqual(
            shipment.pod_status,
            TenantShipment.PodStatus.COMPLETED,
        )


class HardPodMilestoneStatusClampTests(TestCase):
    @patch(
        'iroad_tenants.operation_runtime.latest_state._defer_pod_submitted_until_hard_copy_complete',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_upload_log_is_valid',
        return_value=True,
    )
    def test_milestone_stays_at_delivery_until_hard_copy_complete(
        self,
        _pod_valid,
        _defer,
    ):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            infer_shipment_status_from_milestone_log_rows,
        )

        shipment = SimpleNamespace(
            order_type='COD',
            pod_type=TenantShipment.PodType.HARD,
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
        )
        status = infer_shipment_status_from_milestone_log_rows([], shipment=shipment)
        self.assertEqual(status, TenantShipment.ShipmentStatus.AT_DELIVERY)

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_upload_log_is_valid',
        return_value=True,
    )
    def test_milestone_pod_submitted_when_hard_copy_complete(
        self,
        _pod_valid,
        _hard_pending,
    ):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            infer_shipment_status_from_milestone_log_rows,
        )

        shipment = SimpleNamespace(
            order_type='COD',
            pod_type=TenantShipment.PodType.HARD,
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
        )
        status = infer_shipment_status_from_milestone_log_rows([], shipment=shipment)
        self.assertEqual(status, TenantShipment.ShipmentStatus.POD_SUBMITTED)


class HardPodRepairBeforePromotionTests(TestCase):
    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._pending_hard_pod_custody_exists',
        return_value=True,
    )
    def test_repair_rewinds_pod_submitted_when_custody_submission_pending(
        self,
        _pending,
        _derive,
    ):
        from iroad_tenants.operation_runtime.latest_state import (
            repair_delivered_before_hard_pod_custody,
        )

        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.POD_SUBMITTED,
            pod_type=TenantShipment.PodType.HARD,
            booking=SimpleNamespace(pod_type=TenantShipment.PodType.HARD),
            save=lambda update_fields=None: None,
        )
        self.assertTrue(repair_delivered_before_hard_pod_custody(shipment))
        self.assertEqual(
            shipment.shipment_status,
            TenantShipment.ShipmentStatus.AT_DELIVERY,
        )
