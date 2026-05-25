"""
Empty / movement-only workflow engine tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.operation_execution import _action_is_allowed
from iroad_tenants.operation_runtime.movement_execution_engine import (
    is_movement_only_context,
    movement_action_allowed,
)
from iroad_tenants.operation_runtime.movement_stage_derivation import (
    derive_movement_execution_stage,
)
from iroad_tenants.operation_runtime.movement_state_machine import (
    STAGE_CREATED,
    STAGE_IN_TRANSIT,
    is_movement_start_action,
    movement_impact_allowed_from_current,
)
from tenant_workspace.models import TenantOperationAction, TenantTruckMovementLog


def _movement(status=TenantTruckMovementLog.Status.SCHEDULED, *, empty=True):
    m = MagicMock()
    m.pk = uuid4()
    m.movement_id = m.pk
    m.status = status
    m.movement_source = 'empty' if empty else 'Loaded'
    m.empty_move_reason = 'Depot' if empty else ''
    return m


def _action(code, label, **kwargs):
    a = MagicMock(spec=TenantOperationAction)
    a.action_id = uuid4()
    a.action_code = code
    a.english_label = label
    a.arabic_label = ''
    a.status = TenantOperationAction.Status.ACTIVE
    a.sequence_category = kwargs.get('sequence_category', 'empty_move')
    a.movement_status_impact = kwargs.get('movement_status_impact', '')
    a.shipment_status_impact = ''
    a.booking_status_impact = ''
    a.auto_shipment_post = False
    a.auto_movement_post = False
    a.auto_pod_post = False
    return a


class MovementContextTests(SimpleTestCase):
    def test_movement_only_context(self):
        self.assertTrue(
            is_movement_only_context(
                shipment=None,
                movement=_movement(),
            )
        )
        self.assertFalse(
            is_movement_only_context(
                shipment=MagicMock(),
                movement=_movement(),
            )
        )


class MovementStageTests(SimpleTestCase):
    @patch(
        'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
        return_value={'start_done': False, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    def test_scheduled_without_logs_is_created(self, _mock):
        self.assertEqual(
            derive_movement_execution_stage(_movement()),
            STAGE_CREATED,
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
        return_value={'start_done': True, 'in_transit_done': True, 'arrived_done': False, 'complete_done': False},
    )
    def test_in_progress_in_transit_stage(self, _mock):
        movement = _movement(status=TenantTruckMovementLog.Status.IN_PROGRESS)
        self.assertEqual(
            derive_movement_execution_stage(movement),
            STAGE_IN_TRANSIT,
        )


class MovementPolicyTests(SimpleTestCase):
    def test_start_action_match(self):
        self.assertTrue(is_movement_start_action(_action('EM1', 'Start Movement')))

    def test_forward_impact_scheduled_to_in_progress(self):
        self.assertTrue(
            movement_impact_allowed_from_current(
                current=TenantTruckMovementLog.Status.SCHEDULED,
                impact_status=TenantTruckMovementLog.Status.IN_PROGRESS,
            )
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_execution_engine.movement_executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
        return_value={'start_done': False, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    def test_start_allowed_on_empty_movement(self, _flags, _ids):
        movement = _movement()
        action = _action('EM1', 'Start Movement', movement_status_impact='in_progress')
        self.assertTrue(
            movement_action_allowed(action, movement=movement),
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_execution_engine.movement_executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
        return_value={'start_done': False, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    def test_shipment_only_action_blocked_on_movement(self, _flags, _ids):
        movement = _movement()
        action = _action('A5', 'Depart In Transit', shipment_status_impact='In Transit', sequence_category='job')
        self.assertFalse(
            _action_is_allowed(action, movement=movement, shipment=None),
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_log_milestone_flags',
        return_value={'start_done': True, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_execution_engine.movement_executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
        return_value={'start_done': True, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    def test_in_transit_requires_start(self, _stage_flags, _ids, _val_flags):
        movement = _movement(status=TenantTruckMovementLog.Status.IN_PROGRESS)
        action = _action('EM2', 'In Transit', sequence_category='empty_move')
        self.assertTrue(
            _action_is_allowed(action, movement=movement, shipment=None),
        )
