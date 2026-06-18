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
    STAGE_LOADING,
    STAGE_PICKUP,
    STAGE_PRE_TRANSIT,
    derive_shipment_execution_stage,
    is_pickup_action,
    is_loading_action,
    shipment_allows_pickup_loading_action,
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
        'iroad_tenants.operation_runtime.shipment_execution_stage._shipment_pickup_loading_done',
        return_value=(True, True),
    )
    def test_after_loading_is_pre_transit(self, _mock):
        self.assertEqual(
            derive_shipment_execution_stage(_shipment()),
            STAGE_PRE_TRANSIT,
        )


class PickupLoadingPolicyTests(SimpleTestCase):
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
    def test_auto_shipment_a4_allowed_after_a1_a2_a3(self, _ids, _a1, _a2, _a3, _active):
        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_status = 'Confirmed'
        action = _action('A4', 'Confirm Loaded', auto_shipment_post=True)
        self.assertTrue(_action_is_allowed(action, booking=booking))

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
