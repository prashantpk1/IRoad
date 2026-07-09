"""Tests for dynamic job workflow action policy."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.operation_execution import _action_is_allowed
from iroad_tenants.operation_runtime.workflow_action_policy import (
    action_is_job_close,
    action_requires_cod_order_type,
    filter_shipment_timeline_workflow_actions,
    shipment_workflow_sequence_prerequisites_met,
)

def _action(**kwargs):
    row = MagicMock()
    row.action_id = kwargs.get('action_id', uuid4())
    row.action_code = kwargs.get('code', 'OA-0001')
    row.label = ''
    row.english_label = kwargs.get('label', 'Action')
    row.sequence_number = kwargs.get('sequence_number', 1)
    row.condition_code = kwargs.get('condition_code', '')
    row.auto_treasury_post = kwargs.get('auto_treasury_post', False)
    row.auto_movement_post = kwargs.get('auto_movement_post', False)
    row.auto_shipment_post = kwargs.get('auto_shipment_post', False)
    row.sequence_category = kwargs.get('sequence_category', 'job')
    row.hard_copy_collection = kwargs.get('hard_copy_collection', False)
    row.auto_pod_post = kwargs.get('auto_pod_post', False)
    row.shipment_status_impact = kwargs.get('shipment_status_impact', '')
    row.booking_status_impact = kwargs.get('booking_status_impact', '')
    row.movement_status_impact = kwargs.get('movement_status_impact', '')
    row.status = kwargs.get('status', 'Active')
    return row


class WorkflowActionPolicyTests(SimpleTestCase):
    def test_payment_collection_requires_cod_by_label(self):
        payment = _action(code='OA-0009', label='Payment Collection')
        self.assertTrue(action_requires_cod_order_type(payment))

    def test_pod_label_is_not_cod_payment_action(self):
        pod = _action(code='OA-0008', label='POD')
        self.assertFalse(action_requires_cod_order_type(pod))

    def test_payment_collection_requires_cod_by_condition_code(self):
        payment = _action(
            code='OA-0099',
            label='Cash on Delivery',
            condition_code='Order_Type_must_be_COD',
        )
        self.assertTrue(action_requires_cod_order_type(payment))

    def test_credit_timeline_hides_payment_collection(self):
        actions = [
            _action(code='OA-0006', label='Delivery Arrival', sequence_number=6),
            _action(
                code='OA-0009',
                label='Payment Collection',
                sequence_number=9,
                auto_treasury_post=True,
            ),
            _action(code='OA-0010', label='End Job', sequence_number=10),
        ]
        filtered = filter_shipment_timeline_workflow_actions(
            actions,
            is_booking_job=False,
            is_cod=False,
        )
        self.assertEqual(
            [row.action_code for row in filtered],
            ['OA-0006', 'OA-0010'],
        )

    def test_cod_timeline_keeps_payment_collection(self):
        payment = _action(
            code='OA-0009',
            label='Payment Collection',
            sequence_number=9,
            auto_treasury_post=True,
        )
        filtered = filter_shipment_timeline_workflow_actions(
            [payment],
            is_booking_job=False,
            is_cod=True,
        )
        self.assertEqual([row.action_code for row in filtered], ['OA-0009'])

    def test_shipment_timeline_hides_start_job(self):
        actions = [
            _action(
                code='OA-0001',
                label='Start Job',
                sequence_number=1,
                auto_movement_post=True,
            ),
            _action(code='OA-0002', label='Pickup Arrival', sequence_number=2),
        ]
        filtered = filter_shipment_timeline_workflow_actions(
            actions,
            is_booking_job=False,
            is_cod=False,
        )
        self.assertEqual([row.action_code for row in filtered], ['OA-0002'])

    def test_end_job_not_treated_as_start_job(self):
        end_job = _action(code='OA-0011', label='End Job', sequence_number=11)
        filtered = filter_shipment_timeline_workflow_actions(
            [end_job],
            is_booking_job=False,
            is_cod=False,
        )
        self.assertEqual([row.action_code for row in filtered], ['OA-0011'])
        start = _action(
            code='OA-0001',
            label='Start Job',
            sequence_number=1,
            auto_movement_post=True,
        )
        filtered = filter_shipment_timeline_workflow_actions(
            [start],
            is_booking_job=True,
            is_cod=False,
        )
        self.assertEqual([row.action_code for row in filtered], ['OA-0001'])

    def test_end_job_label_is_job_close(self):
        end_job = _action(code='OA-0011', label='End Job', sequence_number=11)
        self.assertTrue(action_is_job_close(end_job))

    def test_end_job_booking_executed_closes_shipment_semantics(self):
        end_job = _action(
            code='OA-0099',
            label='Finish',
            sequence_number=11,
            booking_status_impact='Executed',
        )
        self.assertTrue(action_is_job_close(end_job))

    @patch(
        'iroad_tenants.operation_runtime.workflow_action_policy.shipment_applicable_workflow_actions',
    )
    @patch(
        'iroad_tenants.operation_runtime.workflow_action_policy.workflow_step_completed_on_shipment',
        side_effect=lambda step, **kwargs: (
            getattr(step, 'action_code', '') == 'OA-0005'
        ),
    )
    def test_sequence_blocks_later_step_until_prior_steps_complete(
        self,
        _step_done,
        mock_workflow,
    ):
        depart = _action(code='OA-0005', label='Departure', sequence_number=5)
        delivery = _action(code='OA-0006', label='Delivery Arrival', sequence_number=6)
        unload_done = _action(
            code='OA-0008',
            label='Unloading Completed',
            sequence_number=8,
        )
        mock_workflow.return_value = [depart, delivery, unload_done]
        shipment = MagicMock()
        shipment.order_type = 'Credit'
        executed = {depart.action_id}

        self.assertTrue(
            shipment_workflow_sequence_prerequisites_met(
                delivery,
                shipment=shipment,
                executed_action_ids=executed,
            ),
        )
        self.assertFalse(
            shipment_workflow_sequence_prerequisites_met(
                unload_done,
                shipment=shipment,
                executed_action_ids=executed,
            ),
        )

    @patch(
        'iroad_tenants.operation_execution._combined_pod_allows_hard_copy_retry',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._combined_pod_allows_digital_recovery',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._hard_pod_blocks_forward_action',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_execution._shipment_has_active_movement',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_departure_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_delivery_arrival_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.workflow_action_policy.shipment_applicable_workflow_actions',
    )
    def test_unloading_completed_blocked_until_delivery_and_start_unloading(
        self,
        mock_workflow,
        _unload,
        _delivery,
        _depart,
        _movement,
        _ids,
        _hard_pod,
        _digital,
        _retry,
    ):
        from tenant_workspace.models import TenantOperationAction, TenantShipment

        depart = _action(code='OA-0005', label='Departure', sequence_number=5)
        delivery = _action(code='OA-0006', label='Delivery Arrival', sequence_number=6)
        start_unload = _action(
            code='OA-0007',
            label='Start Unloading',
            sequence_number=7,
        )
        unload_done = _action(
            code='OA-0008',
            label='Unloading Completed',
            sequence_number=8,
        )
        mock_workflow.return_value = [depart, delivery, start_unload, unload_done]
        unload_done.status = TenantOperationAction.Status.ACTIVE
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.LOADED
        shipment.order_type = 'Credit'
        shipment.collection_status = ''
        self.assertFalse(_action_is_allowed(unload_done, shipment=shipment))

    @patch(
        'iroad_tenants.operation_execution._combined_pod_allows_hard_copy_retry',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._combined_pod_allows_digital_recovery',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._hard_pod_blocks_forward_action',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_execution._shipment_has_active_movement',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_at_or_past_in_transit',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_delivery_arrival_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.workflow_action_policy.shipment_workflow_sequence_prerequisites_met',
        return_value=True,
    )
    def test_delivery_arrival_allowed_without_movement_when_in_transit(
        self,
        _sequence,
        _delivery_done,
        _in_transit,
        _movement,
        _ids,
        _hard_pod,
        _digital,
        _retry,
    ):
        from tenant_workspace.models import TenantShipment

        delivery = _action(code='OA-0006', label='Delivery Arrival', sequence_number=6)
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.LOADED
        shipment.order_type = 'Credit'
        shipment.collection_status = ''
        self.assertTrue(_action_is_allowed(delivery, shipment=shipment))
