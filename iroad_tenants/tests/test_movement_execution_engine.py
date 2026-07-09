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
    STAGE_STARTED,
    is_movement_start_action,
    movement_impact_allowed_from_current,
)
from iroad_tenants.operation_runtime.shipment_execution_stage import STAGE_PRE_TRANSIT
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
    a.prerequisite_action_codes = kwargs.get('prerequisite_action_codes', '')
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
        return_value={'start_done': False, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    def test_completed_column_without_logs_is_created_not_terminal(self, _mock):
        movement = _movement(status=TenantTruckMovementLog.Status.COMPLETED)
        self.assertEqual(
            derive_movement_execution_stage(movement),
            STAGE_CREATED,
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
        return_value={'start_done': False, 'in_transit_done': False, 'arrived_done': False, 'complete_done': True},
    )
    def test_completed_column_with_complete_log_is_completed(self, _mock):
        movement = _movement(status=TenantTruckMovementLog.Status.COMPLETED)
        from iroad_tenants.operation_runtime.movement_state_machine import STAGE_COMPLETED

        self.assertEqual(
            derive_movement_execution_stage(movement),
            STAGE_COMPLETED,
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
        return_value={'start_done': False, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    def test_in_progress_without_logs_is_created(self, _mock):
        movement = _movement(status=TenantTruckMovementLog.Status.IN_PROGRESS)
        self.assertEqual(
            derive_movement_execution_stage(movement),
            STAGE_CREATED,
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
        return_value={'start_done': True, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    def test_in_progress_after_start_is_started(self, _mock):
        movement = _movement(status=TenantTruckMovementLog.Status.IN_PROGRESS)
        from iroad_tenants.operation_runtime.movement_state_machine import STAGE_STARTED

        self.assertEqual(
            derive_movement_execution_stage(movement),
            STAGE_STARTED,
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
        return_value={'start_done': True, 'in_transit_done': True, 'arrived_done': False, 'complete_done': False},
    )
    def test_scheduled_in_transit_milestones_use_in_transit_stage(self, _mock):
        movement = _movement(status=TenantTruckMovementLog.Status.SCHEDULED)
        self.assertEqual(
            derive_movement_execution_stage(movement),
            STAGE_IN_TRANSIT,
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
        return_value={'start_done': True, 'in_transit_done': True, 'arrived_done': True, 'complete_done': False},
    )
    def test_completed_column_without_em4_log_uses_arrived_stage(self, _mock):
        movement = _movement(status=TenantTruckMovementLog.Status.COMPLETED)
        from iroad_tenants.operation_runtime.movement_state_machine import STAGE_ARRIVED

        self.assertEqual(
            derive_movement_execution_stage(movement),
            STAGE_ARRIVED,
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


class MovementReconcileTests(SimpleTestCase):
    def test_terminal_completed_column_without_logs_uses_scheduled(self):
        from iroad_tenants.operation_runtime.workflow_state_reconciler import (
            reconcile_movement_execution_state,
        )

        movement = _movement(status=TenantTruckMovementLog.Status.COMPLETED)
        with patch(
            'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
            return_value={
                'start_done': False,
                'in_transit_done': False,
                'arrived_done': False,
                'complete_done': False,
            },
        ):
            state = reconcile_movement_execution_state(movement, prefetched_logs=[])

        self.assertEqual(
            state['authoritative_status'],
            TenantTruckMovementLog.Status.SCHEDULED,
        )
        self.assertEqual(state['execution_sub_stage'], STAGE_CREATED)
        self.assertTrue(state['drift']['has_drift'])
        self.assertEqual(
            state['drift']['reason'],
            'terminal_column_without_action_logs',
        )

    def test_scheduled_column_without_logs_stays_scheduled(self):
        from iroad_tenants.operation_runtime.workflow_state_reconciler import (
            reconcile_movement_execution_state,
        )

        movement = _movement(status=TenantTruckMovementLog.Status.SCHEDULED)
        with patch(
            'iroad_tenants.operation_runtime.movement_stage_derivation.movement_log_milestone_flags',
            return_value={
                'start_done': False,
                'in_transit_done': False,
                'arrived_done': False,
                'complete_done': False,
            },
        ):
            state = reconcile_movement_execution_state(movement, prefetched_logs=[])

        self.assertEqual(
            state['authoritative_status'],
            TenantTruckMovementLog.Status.SCHEDULED,
        )
        self.assertFalse(state['drift']['has_drift'])


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
        'iroad_tenants.operation_runtime.movement_action_validator.movement_log_milestone_flags',
        return_value={'start_done': False, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_workflow_column_for_policy',
        return_value=TenantTruckMovementLog.Status.SCHEDULED,
    )
    def test_em1_allowed_when_column_in_progress_without_logs(
        self,
        _workflow_column,
        _flags,
        _ids,
    ):
        movement = _movement(status=TenantTruckMovementLog.Status.IN_PROGRESS)
        action = _action('EM1', 'Start Movement', movement_status_impact='in_progress')
        self.assertTrue(
            movement_action_allowed(action, movement=movement),
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_execution_engine.movement_executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator._movement_executed_action_codes',
        return_value={'EM1'},
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.derive_movement_execution_stage',
        return_value=STAGE_STARTED,
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_log_milestone_flags',
        return_value={'start_done': True, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_workflow_column_for_policy',
        return_value=TenantTruckMovementLog.Status.IN_PROGRESS,
    )
    def test_em2_allowed_after_em1_logged(self, _workflow_column, _flags, _stage, _codes, _ids):
        movement = _movement(status=TenantTruckMovementLog.Status.IN_PROGRESS)
        em2 = _action(
            'EM2',
            'Depart Empty',
            sequence_category='empty_move',
            prerequisite_action_codes='EM1',
        )
        self.assertTrue(
            movement_action_allowed(em2, movement=movement),
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_execution_engine.movement_executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator._movement_executed_action_codes',
        return_value={'EM1', 'EM2'},
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.derive_movement_execution_stage',
        return_value=STAGE_IN_TRANSIT,
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_log_milestone_flags',
        return_value={'start_done': True, 'in_transit_done': True, 'arrived_done': False, 'complete_done': False},
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_workflow_column_for_policy',
        return_value=TenantTruckMovementLog.Status.IN_PROGRESS,
    )
    def test_em3_allowed_after_em2_logged(self, _workflow_column, _flags, _stage, _codes, _ids):
        movement = _movement(status=TenantTruckMovementLog.Status.IN_PROGRESS)
        em3 = _action(
            'EM3',
            'Arrival At Destination',
            sequence_category='empty_move',
            prerequisite_action_codes='EM2',
        )
        self.assertTrue(
            movement_action_allowed(em3, movement=movement),
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_execution_engine.movement_executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator._movement_executed_action_codes',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.derive_movement_execution_stage',
        return_value=STAGE_CREATED,
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_log_milestone_flags',
        return_value={'start_done': False, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_workflow_column_for_policy',
        return_value=TenantTruckMovementLog.Status.SCHEDULED,
    )
    def test_em2_blocked_until_em1_logged(self, _workflow_column, _flags, _stage, _codes, _ids):
        movement = _movement()
        em2 = _action(
            'EM2',
            'Depart Empty',
            sequence_category='empty_move',
            prerequisite_action_codes='EM1',
        )
        self.assertFalse(
            movement_action_allowed(em2, movement=movement),
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

    @patch('iroad_tenants.operation_execution._shipment_has_active_movement', return_value=False)
    @patch('iroad_tenants.operation_execution._executed_action_ids', return_value=set())
    def test_depart_in_transit_blocked_when_shipment_has_no_movement(self, _ids, _movement_guard):
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = 'Loaded'
        shipment.order_type = 'Credit'
        action = _action('A5', 'Depart In Transit', sequence_category='job')
        action.movement_status_impact = 'In_Progress'
        action.shipment_status_impact = 'In_Transit'
        self.assertFalse(
            _action_is_allowed(action, shipment=shipment),
        )

    @patch('iroad_tenants.operation_execution._shipment_has_active_movement', return_value=False)
    @patch('iroad_tenants.operation_execution._executed_action_ids', return_value=set())
    def test_confirm_loaded_allowed_when_shipment_has_no_movement(self, _ids, _movement_guard):
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = 'Created'
        shipment.order_type = 'Credit'
        action = _action('A4', 'Confirm Loaded', sequence_category='job')
        action.auto_shipment_post = True
        action.movement_status_impact = 'In_Progress'
        action.shipment_status_impact = ''
        self.assertTrue(
            _action_is_allowed(action, shipment=shipment),
        )

    @patch('iroad_tenants.operation_execution._shipment_has_active_movement', return_value=True)
    @patch('iroad_tenants.operation_execution._executed_action_ids', return_value=set())
    @patch(
        'iroad_tenants.operation_execution.derive_shipment_execution_stage',
        return_value=STAGE_PRE_TRANSIT,
    )
    def test_depart_in_transit_allowed_when_shipment_has_movement(self, _stage, _ids, _movement_guard):
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = 'Loaded'
        shipment.order_type = 'Credit'
        action = _action('A5', 'Depart In Transit', sequence_category='job')
        action.movement_status_impact = 'In_Progress'
        action.shipment_status_impact = 'In_Transit'
        self.assertTrue(
            _action_is_allowed(action, shipment=shipment),
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

    @patch(
        'iroad_tenants.operation_runtime.movement_execution_engine.movement_executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator._movement_executed_action_codes',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.validate_movement_completion_stage',
        return_value=None,
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator._empty_move_catalog_has_arrived_action',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_log_milestone_flags',
        return_value={
            'start_done': True,
            'in_transit_done': True,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.derive_movement_execution_stage',
        return_value=STAGE_IN_TRANSIT,
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_workflow_column_for_policy',
        return_value=TenantTruckMovementLog.Status.IN_PROGRESS,
    )
    def test_three_step_end_job_allowed_after_departure(
        self,
        _workflow_column,
        _stage,
        _flags,
        _no_arrived_step,
        _completion_ok,
        _executed_codes,
        _ids,
    ):
        movement = _movement(status=TenantTruckMovementLog.Status.IN_PROGRESS)
        end_job = _action(
            'OA-0016',
            'End Job',
            sequence_category='empty_move',
            movement_status_impact='completed',
            prerequisite_action_codes='OA-0015',
        )
        self.assertTrue(
            movement_action_allowed(end_job, movement=movement),
        )

    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator._ordered_empty_move_catalog_actions',
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_execution_engine.movement_executed_action_ids',
        return_value=set(),
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_log_milestone_flags',
        return_value={'start_done': False, 'in_transit_done': False, 'arrived_done': False, 'complete_done': False},
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.derive_movement_execution_stage',
        return_value=STAGE_CREATED,
    )
    @patch(
        'iroad_tenants.operation_runtime.movement_action_validator.movement_workflow_column_for_policy',
        return_value=TenantTruckMovementLog.Status.SCHEDULED,
    )
    def test_empty_move_start_allowed_by_sequence_category(
        self,
        _workflow_column,
        _stage,
        _flags,
        _ids,
        mock_catalog,
    ):
        movement = _movement()
        start = _action(
            'OA-0014',
            'Start Job',
            sequence_category='empty_move',
            movement_status_impact='In_Progress',
            prerequisite_action_codes='EM1',
        )
        start.auto_shipment_post = True
        start.sequence_number = 1
        mock_catalog.return_value = [start]
        self.assertTrue(
            movement_action_allowed(start, movement=movement),
        )
