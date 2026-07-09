"""
Shipment execution sub-stage and A2/A3 shipment-bound policy tests.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.operation_execution import _action_is_allowed, get_allowed_actions
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    STAGE_IN_TRANSIT,
    STAGE_LOADING,
    STAGE_PICKUP,
    STAGE_PRE_TRANSIT,
    derive_shipment_execution_stage,
    is_delivery_arrival_action,
    is_departure_action,
    is_loading_action,
    is_pickup_action,
    is_unloading_action,
    shipment_allows_pickup_loading_action,
    shipment_allows_unloading_action,
    shipment_at_or_past_in_transit,
)
from tenant_workspace.models import TenantOperationAction, TenantShipment


def _action(code, label, **kwargs):
    a = MagicMock(spec=TenantOperationAction)
    a.action_id = uuid4()
    a.action_code = code
    a.english_label = label
    a.arabic_label = ''
    a.status = TenantOperationAction.Status.ACTIVE
    a.shipment_status_impact = kwargs.get('shipment_status_impact', '')
    a.booking_status_impact = kwargs.get('booking_status_impact', '')
    a.auto_shipment_post = kwargs.get('auto_shipment_post', False)
    a.auto_movement_post = kwargs.get('auto_movement_post', False)
    a.auto_pod_post = kwargs.get('auto_pod_post', False)
    a.hard_copy_collection = False
    a.movement_status_impact = ''
    return a


def _shipment(status=TenantShipment.ShipmentStatus.LOADED):
    s = MagicMock()
    s.pk = uuid4()
    s.shipment_id = s.pk
    s.shipment_status = status
    s.order_type = 'Standard'
    s.collection_status = ''
    return s


class ShipmentStageDerivationTests(SimpleTestCase):
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(False, False),
    )
    def test_loaded_without_logs_is_pickup_stage(self, _mock):
        self.assertEqual(
            derive_shipment_execution_stage(_shipment()),
            STAGE_PICKUP,
        )

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(True, False),
    )
    def test_after_pickup_is_loading_stage(self, _mock):
        self.assertEqual(
            derive_shipment_execution_stage(_shipment()),
            STAGE_PRE_TRANSIT,
        )

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_departure_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(True, True),
    )
    def test_after_loading_is_pre_transit(self, _mock, _depart):
        self.assertEqual(
            derive_shipment_execution_stage(_shipment()),
            STAGE_PRE_TRANSIT,
        )


class PickupLoadingPolicyTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self._workflow_patch = patch(
            'iroad_tenants.operation_runtime.workflow_action_policy.shipment_applicable_workflow_actions',
            return_value=[],
        )
        self._workflow_patch.start()

    def tearDown(self):
        self._workflow_patch.stop()
        super().tearDown()

    def test_action_match_helpers(self):
        self.assertTrue(is_pickup_action(_action('A2', 'Pickup Arrival')))
        self.assertTrue(is_loading_action(_action('A3', 'Start Loading')))
        self.assertFalse(is_pickup_action(_action('A6', 'Arrival at Delivery')))

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(False, False),
    )
    def test_a2_allowed_on_shipment_early_lifecycle(self, _mock):
        action = _action('A2', 'Pickup')
        shipment = _shipment()
        self.assertTrue(
            shipment_allows_pickup_loading_action(action, shipment),
        )

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(False, False),
    )
    def test_a3_blocked_until_pickup_done(self, _mock):
        action = _action('A3', 'Start Loading')
        shipment = _shipment()
        self.assertFalse(
            shipment_allows_pickup_loading_action(action, shipment),
        )

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(True, False),
    )
    def test_a3_allowed_after_pickup(self, _mock):
        action = _action('A3', 'Start Loading')
        shipment = _shipment()
        self.assertTrue(
            shipment_allows_pickup_loading_action(action, shipment),
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
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(False, False),
    )
    def test_action_is_allowed_permits_a2_on_shipment(self, _logs, _movement, _ids):
        action = _action('A2', 'Pickup')
        shipment = _shipment()
        self.assertTrue(
            _action_is_allowed(action, shipment=shipment),
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
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(False, False),
    )
    def test_action_is_allowed_blocks_a2_when_in_transit(self, _logs, _movement, _ids):
        action = _action('A2', 'Pickup')
        shipment = _shipment(status=TenantShipment.ShipmentStatus.IN_TRANSIT)
        self.assertFalse(
            _action_is_allowed(action, shipment=shipment),
        )


class BookingOnlyRegressionTests(SimpleTestCase):
    @patch(
        'iroad_tenants.operation_execution._booking_has_active_shipment',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
        return_value=set(),
    )
    def test_booking_a2_still_blocked_when_active_shipment_exists(self, _ids, _active):
        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_status = 'Confirmed'
        action = _action('A2', 'Pickup Arrival')
        self.assertFalse(
            _action_is_allowed(action, booking=booking),
        )

    @patch(
        'iroad_tenants.operation_execution._booking_has_active_shipment',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_loading_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_pickup_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_start_job_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
        return_value=set(),
    )
    def test_auto_shipment_a4_blocked_until_loading_done(self, _ids, _a1, _a2, _a3, _active):
        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_status = 'Confirmed'
        action = _action('A4', 'Confirm Loaded', auto_shipment_post=True)
        self.assertFalse(_action_is_allowed(action, booking=booking))

    @patch(
        'iroad_tenants.operation_execution._booking_has_born_shipment_line',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_has_active_shipment',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_loading_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_pickup_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_start_job_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
        return_value=set(),
    )
    def test_auto_shipment_a4_allowed_after_a1_a2_a3(self, _ids, _a1, _a2, _a3, _active, _born):
        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_status = 'Confirmed'
        action = _action('A4', 'Confirm Loaded', auto_shipment_post=True)
        self.assertTrue(_action_is_allowed(action, booking=booking))

    @patch(
        'iroad_tenants.operation_execution._booking_has_born_shipment_line',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_has_active_shipment',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_loading_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_pickup_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_start_job_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
        return_value=set(),
    )
    def test_auto_shipment_a4_blocked_when_outbound_row_already_born(
        self,
        _ids,
        _a1,
        _a2,
        _a3,
        _active,
        _born,
    ):
        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_status = 'Confirmed'
        action = _action('A4', 'Confirm Loaded', auto_shipment_post=True)
        self.assertFalse(_action_is_allowed(action, booking=booking))

    @patch(
        'iroad_tenants.operation_execution._booking_has_active_shipment',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_start_job_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
        return_value=set(),
    )
    def test_booking_a2_blocked_until_start_job(self, _ids, _a1, _active):
        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_status = 'Confirmed'
        action = _action('A2', 'Pickup Arrival')
        self.assertFalse(_action_is_allowed(action, booking=booking))

    @patch(
        'iroad_tenants.operation_execution.TenantOperationActionLog',
    )
    def test_execution_date_alone_does_not_count_as_start_job(self, mock_log_model):
        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.execution_date = date(2026, 6, 17)
        mock_log_model.objects.filter.return_value.exclude.return_value.select_related.return_value = []
        from iroad_tenants.operation_execution import _booking_start_job_done

        self.assertFalse(_booking_start_job_done(booking))

    @patch(
        'iroad_tenants.operation_execution._booking_has_active_shipment',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_loading_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_pickup_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._booking_start_job_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
        return_value=set(),
    )
    def test_auto_shipment_a4_blocked_until_start_job_even_if_loading_logged(
        self,
        _ids,
        _a1,
        _a2,
        _a3,
        _active,
    ):
        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_status = 'Confirmed'
        action = _action('A4', 'Confirm Loaded', auto_shipment_post=True)
        self.assertFalse(_action_is_allowed(action, booking=booking))

    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
        return_value=set(),
    )
    def test_booking_only_blocks_shipment_phase_actions_like_a8(self, _ids):
        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_status = 'Confirmed'
        action = _action('A8', 'Unloading Completed', movement_status_impact='Completed')
        self.assertFalse(_action_is_allowed(action, booking=booking))

    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_execution._shipment_has_active_movement',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_execution._shipment_pickup_loading_done',
        return_value=(False, False),
    )
    def test_shipment_a4_blocked_until_pickup_and_loading(self, _logs, _movement, _ids):
        action = _action(
            'A4',
            'Confirm Loaded',
            shipment_status_impact=TenantShipment.ShipmentStatus.LOADED,
        )
        shipment = _shipment()
        self.assertFalse(_action_is_allowed(action, shipment=shipment))


class UnloadingPolicyTests(SimpleTestCase):
    """Policy unit tests — sequence gate disabled (no tenant workflow catalog in SimpleTestCase)."""

    def setUp(self):
        super().setUp()
        self._workflow_patch = patch(
            'iroad_tenants.operation_runtime.workflow_action_policy.shipment_applicable_workflow_actions',
            return_value=[],
        )
        self._workflow_patch.start()

    def tearDown(self):
        self._workflow_patch.stop()
        super().tearDown()

    def test_unloading_action_match_helpers(self):
        self.assertTrue(is_unloading_action(_action('OA-0007', 'Start Unloading')))
        self.assertTrue(
            is_delivery_arrival_action(
                _action(
                    'OA-0006',
                    'Delivery Arrival',
                    shipment_status_impact=TenantShipment.ShipmentStatus.AT_DELIVERY,
                ),
            ),
        )
        self.assertFalse(
            is_delivery_arrival_action(_action('OA-0007', 'Start Unloading')),
        )

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_delivery_milestones_done',
        return_value=(True, False),
    )
    def test_unloading_allowed_after_delivery_arrival(self, _mock):
        action = _action('OA-0007', 'Start Unloading')
        shipment = _shipment(status=TenantShipment.ShipmentStatus.AT_DELIVERY)
        self.assertTrue(shipment_allows_unloading_action(action, shipment))

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_delivery_milestones_done',
        return_value=(False, False),
    )
    def test_unloading_blocked_until_delivery_arrival(self, _mock):
        action = _action('OA-0007', 'Start Unloading')
        shipment = _shipment(status=TenantShipment.ShipmentStatus.IN_TRANSIT)
        self.assertFalse(shipment_allows_unloading_action(action, shipment))

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
        'iroad_tenants.operation_execution.shipment_unloading_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_completed_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_delivery_milestones_done',
        return_value=(True, False),
    )
    def test_pod_blocked_at_delivery_until_unloading_logged(
        self,
        _milestones,
        _unload_completed,
        _unload_done,
        _movement,
        _ids,
        _hard_pod,
        _digital,
        _retry,
    ):
        action = _action(
            'OA-0008',
            'POD',
            auto_pod_post=True,
            shipment_status_impact=TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )
        shipment = _shipment(status=TenantShipment.ShipmentStatus.AT_DELIVERY)
        self.assertFalse(_action_is_allowed(action, shipment=shipment))

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
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_delivery_milestones_done',
        return_value=(False, False),
    )
    def test_pod_blocked_from_in_transit_until_delivery_and_unloading(
        self,
        _milestones,
        _movement,
        _ids,
        _hard_pod,
        _digital,
        _retry,
    ):
        action = _action(
            'OA-0008',
            'POD',
            auto_pod_post=True,
            shipment_status_impact=TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )
        shipment = _shipment(status=TenantShipment.ShipmentStatus.IN_TRANSIT)
        self.assertFalse(_action_is_allowed(action, shipment=shipment))

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
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_delivery_arrival_done',
        return_value=False,
    )
    def test_delivery_arrival_allowed_after_out_of_order_pod_status(
        self,
        _delivery_done,
        _movement,
        _ids,
        _hard_pod,
        _digital,
        _retry,
    ):
        action = _action(
            'OA-0006',
            'Delivery Arrival',
            shipment_status_impact=TenantShipment.ShipmentStatus.AT_DELIVERY,
        )
        shipment = _shipment(status=TenantShipment.ShipmentStatus.POD_SUBMITTED)
        self.assertTrue(_action_is_allowed(action, shipment=shipment))


class DepartureLogStageTests(SimpleTestCase):
    def test_departure_action_matches_tenant_label(self):
        self.assertTrue(is_departure_action(_action('OA-0005', 'Departure')))

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(True, True),
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_departure_done',
        return_value=True,
    )
    def test_loaded_column_advances_to_in_transit_stage_after_departure_log(
        self,
        _depart_done,
        _loading,
    ):
        shipment = _shipment(status=TenantShipment.ShipmentStatus.LOADED)
        self.assertEqual(
            derive_shipment_execution_stage(shipment),
            STAGE_IN_TRANSIT,
        )
        self.assertTrue(shipment_at_or_past_in_transit(shipment))

    @patch(
        'iroad_tenants.operation_runtime.workflow_action_policy.shipment_applicable_workflow_actions',
        return_value=[],
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
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_delivery_arrival_done',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_at_or_past_in_transit',
        return_value=True,
    )
    def test_delivery_arrival_allowed_when_column_still_loaded_after_departure(
        self,
        _in_transit,
        _delivery_done,
        _movement,
        _ids,
        _hard_pod,
        _digital,
        _retry,
        _workflow,
    ):
        action = _action('OA-0020', 'Delivery Arrival')
        shipment = _shipment(status=TenantShipment.ShipmentStatus.LOADED)
        self.assertTrue(_action_is_allowed(action, shipment=shipment))


class InferShipmentStatusFromMilestonesTests(SimpleTestCase):
    def _log(self, action):
        log = MagicMock()
        log.operation_action = action
        return log

    def test_unloading_completed_maps_to_delivered_for_credit(self):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            infer_shipment_status_from_milestone_log_rows,
        )

        logs = [
            self._log(_action('OA-0004', 'Loading Completed', auto_shipment_post=True)),
            self._log(_action('OA-0005', 'Departure')),
            self._log(_action('OA-0006', 'Delivery Arrival')),
            self._log(_action('OA-0007', 'Start Unloading')),
            self._log(_action('OA-0008', 'Unloading Completed')),
        ]
        shipment = _shipment(status=TenantShipment.ShipmentStatus.AT_DELIVERY)
        shipment.order_type = 'Credit'
        status = infer_shipment_status_from_milestone_log_rows(logs, shipment=shipment)
        self.assertEqual(status, TenantShipment.ShipmentStatus.DELIVERED)

    def test_unloading_completed_maps_to_at_delivery_for_cod(self):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            infer_shipment_status_from_milestone_log_rows,
        )

        logs = [
            self._log(_action('OA-0004', 'Loading Completed', auto_shipment_post=True)),
            self._log(_action('OA-0005', 'Departure')),
            self._log(_action('OA-0006', 'Delivery Arrival')),
            self._log(_action('OA-0007', 'Start Unloading')),
            self._log(_action('OA-0008', 'Unloading Completed')),
        ]
        shipment = _shipment(status=TenantShipment.ShipmentStatus.AT_DELIVERY)
        shipment.order_type = 'COD'
        status = infer_shipment_status_from_milestone_log_rows(logs, shipment=shipment)
        self.assertEqual(status, TenantShipment.ShipmentStatus.AT_DELIVERY)

    def test_unloading_completed_maps_to_at_delivery_without_shipment(self):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            infer_shipment_status_from_milestone_log_rows,
        )

        logs = [
            self._log(_action('OA-0004', 'Loading Completed', auto_shipment_post=True)),
            self._log(_action('OA-0005', 'Departure')),
            self._log(_action('OA-0006', 'Delivery Arrival')),
            self._log(_action('OA-0007', 'Start Unloading')),
            self._log(_action('OA-0008', 'Unloading Completed')),
        ]
        status = infer_shipment_status_from_milestone_log_rows(logs)
        self.assertEqual(status, TenantShipment.ShipmentStatus.AT_DELIVERY)

    def test_departure_only_maps_to_in_transit(self):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            infer_shipment_status_from_milestone_log_rows,
        )

        logs = [
            self._log(_action('OA-0004', 'Loading Completed', auto_shipment_post=True)),
            self._log(_action('OA-0005', 'Departure')),
        ]
        status = infer_shipment_status_from_milestone_log_rows(logs)
        self.assertEqual(status, TenantShipment.ShipmentStatus.IN_TRANSIT)

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_prerequisites_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_departure_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(True, True),
    )
    def test_derive_stage_pod_when_column_still_loaded_after_unloading(
        self,
        _pickup_loading,
        _departure,
        _pod_ready,
    ):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            STAGE_POD,
            derive_shipment_execution_stage,
        )

        shipment = _shipment(status=TenantShipment.ShipmentStatus.LOADED)
        self.assertEqual(
            derive_shipment_execution_stage(shipment),
            STAGE_POD,
        )

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_upload_log_is_valid',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_prerequisites_done',
        return_value=True,
    )
    def test_derive_stage_pod_when_at_delivery_and_upload_pending(
        self,
        _pod_ready,
        _upload_valid,
    ):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            STAGE_POD,
            derive_shipment_execution_stage,
        )

        shipment = _shipment(status=TenantShipment.ShipmentStatus.AT_DELIVERY)
        self.assertEqual(derive_shipment_execution_stage(shipment), STAGE_POD)

    def test_cod_in_transit_stage_is_in_transit_not_cod(self):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            STAGE_IN_TRANSIT,
            derive_shipment_execution_stage,
        )

        shipment = _shipment(status=TenantShipment.ShipmentStatus.IN_TRANSIT)
        shipment.order_type = 'COD'
        shipment.collection_status = TenantShipment.CollectionStatus.PENDING
        self.assertEqual(
            derive_shipment_execution_stage(shipment),
            STAGE_IN_TRANSIT,
        )

    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_upload_log_is_valid',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_prerequisites_done',
        return_value=True,
    )
    def test_derive_stage_pod_when_delivered_and_upload_pending(
        self,
        _pod_ready,
        _upload_valid,
    ):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            STAGE_POD,
            derive_shipment_execution_stage,
        )

        shipment = _shipment(status=TenantShipment.ShipmentStatus.DELIVERED)
        self.assertEqual(derive_shipment_execution_stage(shipment), STAGE_POD)

    @patch(
        'iroad_tenants.operation_runtime.workflow_action_policy.shipment_workflow_sequence_prerequisites_met',
        return_value=True,
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
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_prerequisites_done',
        return_value=True,
    )
    def test_label_only_pod_allowed_after_unloading(
        self,
        _pod_ready,
        _movement,
        _ids,
        _hard_pod,
        _digital,
        _retry,
        _seq,
    ):
        action = _action('OA-0009', 'POD')
        shipment = _shipment(status=TenantShipment.ShipmentStatus.LOADED)
        self.assertTrue(_action_is_allowed(action, shipment=shipment))

    @patch(
        'iroad_tenants.operation_runtime.workflow_action_policy.shipment_workflow_sequence_prerequisites_met',
        return_value=True,
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
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_upload_log_is_valid',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_pod_prerequisites_done',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._shipment_has_active_movement',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_execution._executed_action_ids',
    )
    def test_label_only_pod_allowed_when_prior_log_invalid(
        self,
        mock_executed_ids,
        _movement,
        _pod_ready,
        _upload_valid,
        _hard_pod,
        _digital,
        _retry,
        _seq,
    ):
        action = _action('OA-0009', 'POD')
        mock_executed_ids.return_value = {action.action_id}
        shipment = _shipment(status=TenantShipment.ShipmentStatus.AT_DELIVERY)
        self.assertTrue(
            _action_is_allowed(
                action,
                shipment=shipment,
                executed_action_ids={action.action_id},
            ),
        )


class ShipmentPodUploadValidityTests(SimpleTestCase):
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pod_upload_substantively_complete',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_logs_for_milestones',
        return_value=[],
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._pod_upload_timestamps_from_logs',
    )
    @patch(
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_delivery_milestones_done',
        return_value=(True, True),
    )
    def test_pod_log_not_valid_when_capture_still_outstanding(
        self,
        _milestones,
        mock_ts,
        _logs,
        _substantive,
    ):
        from datetime import datetime, timezone

        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            shipment_pod_upload_log_is_valid,
        )

        now = datetime.now(tz=timezone.utc)
        mock_ts.return_value = (now, now, now)
        shipment = _shipment(status=TenantShipment.ShipmentStatus.AT_DELIVERY)
        shipment.pod_status = TenantShipment.PodStatus.NOT_COMPLETED
        self.assertFalse(shipment_pod_upload_log_is_valid(shipment))

    def test_label_only_pod_substantively_complete_with_gps_only(self):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            _shipment_pod_upload_substantively_complete,
        )

        action = _action('OA-0009', 'POD', auto_pod_post=False)
        log = MagicMock()
        log.operation_action = action
        log.latitude = '22.29400'
        log.longitude = '73.13750'
        log.log_date = None
        log.created_at = None

        shipment = _shipment(status=TenantShipment.ShipmentStatus.DELIVERED)
        with patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_logs_for_milestones',
            return_value=[log],
        ):
            self.assertTrue(_shipment_pod_upload_substantively_complete(shipment))
