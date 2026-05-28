"""
Shipment execution sub-stage and A2/A3 shipment-bound policy tests.
"""

from __future__ import annotations

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
        action = _action('A2', 'Pickup')
        self.assertFalse(
            _action_is_allowed(action, booking=booking),
        )
