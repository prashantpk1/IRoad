"""
Unit tests for dashboard empty-move selection and projection.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.dashboard.dto.driver_empty_move_selection import (
    DriverEmptyMoveSelectionResult,
)
from mobile_api.dashboard.projections.movement_projection import (
    build_empty_move_card,
    build_movement_summary,
)
from mobile_api.dashboard.selectors import movement_selection_policy as policy
from mobile_api.dashboard.selectors.dashboard_movement_selector import (
    DashboardMovementSelector,
    select_current_driver_empty_move,
)
from mobile_api.dashboard.services.movement_projection_service import (
    MovementProjectionService,
)
from iroad_tenants.operation_runtime.movement_state_machine import (
    STAGE_CREATED,
    STAGE_IN_TRANSIT,
)
from tenant_workspace.models import TenantTruckMovementLog


def _driver(pk=None):
    d = MagicMock()
    d.pk = pk or uuid4()
    d.driver_id = d.pk
    return d


def _mock_movement_queryset(movements):
    """Mock ORM chain ending in a sliceable ordered queryset."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.exclude.return_value = qs
    ordered = list(movements)

    class _Sliceable:
        def __iter__(self):
            return iter(ordered)

        def __getitem__(self, item):
            if isinstance(item, slice):
                return ordered[item]
            return ordered[item]

    qs.order_by.return_value = _Sliceable()
    return qs


def _movement(
    *,
    movement_source='empty',
    empty_move_reason='Depot',
    status=TenantTruckMovementLog.Status.SCHEDULED,
    movement_date=None,
    sequence=1,
    driver_id=None,
    shipment_id=None,
    movement_no='EM-1',
    booking_id=None,
):
    m = MagicMock()
    m.pk = uuid4()
    m.movement_id = m.pk
    m.movement_no = movement_no
    m.movement_source = movement_source
    m.empty_move_reason = empty_move_reason
    m.status = status
    m.movement_date = movement_date or date(2026, 5, 20)
    m.movement_sequence = sequence
    m.driver_id = driver_id
    m.shipment_id = shipment_id
    m.booking_id = booking_id
    return m


class MovementSelectionPolicyTests(SimpleTestCase):
    def _empty_flags(self):
        return {
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        }

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    def test_active_empty_move_by_source(self, _mock_flags):
        driver = _driver()
        movement = _movement(driver_id=driver.pk)
        self.assertTrue(policy.is_active_empty_move(movement))
        self.assertTrue(policy.driver_assigned_to_movement(driver, movement))

    def test_completed_movement_excluded(self):
        movement = _movement(
            status=TenantTruckMovementLog.Status.COMPLETED,
            driver_id=uuid4(),
        )
        self.assertFalse(policy.is_active_empty_move(movement))

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': True,
            'in_transit_done': True,
            'arrived_done': True,
            'complete_done': True,
        },
    )
    def test_complete_log_excludes_even_when_column_in_progress(self, _mock_flags):
        movement = _movement(
            status=TenantTruckMovementLog.Status.IN_PROGRESS,
            driver_id=uuid4(),
        )
        self.assertFalse(policy.is_active_empty_move(movement))

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    def test_cancelled_movement_excluded(self, _mock_flags):
        movement = _movement(
            status=TenantTruckMovementLog.Status.CANCELLED,
            driver_id=uuid4(),
        )
        self.assertFalse(policy.is_active_empty_move(movement))

    def test_loaded_shipment_movement_excluded(self):
        movement = _movement(
            movement_source='Loaded',
            empty_move_reason='',
            shipment_id=uuid4(),
            driver_id=uuid4(),
        )
        self.assertTrue(policy.is_shipment_linked_loaded_movement(movement))
        self.assertFalse(policy.is_active_empty_move(movement))

    def test_loaded_source_without_shipment_excluded(self):
        movement = _movement(
            movement_source='Loaded',
            empty_move_reason='',
            driver_id=uuid4(),
        )
        self.assertFalse(policy.is_active_empty_move(movement))

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    def test_movement_ordering_picks_earlier_date(self, _mock_flags):
        driver = _driver()
        later = _movement(
            movement_date=date(2026, 6, 1),
            driver_id=driver.pk,
            movement_no='EM-LATE',
        )
        earlier = _movement(
            movement_date=date(2026, 5, 1),
            driver_id=driver.pk,
            movement_no='EM-EARLY',
        )
        picked = policy.select_active_empty_move_from_list(
            driver,
            [later, earlier],
        )
        self.assertEqual(picked.movement_no, 'EM-EARLY')

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    def test_assignment_validation_wrong_driver_skipped(self, _mock_flags):
        driver = _driver()
        other = _movement(driver_id=uuid4())
        self.assertIsNone(
            policy.select_active_empty_move_from_list(driver, [other]),
        )

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_execution_stage',
        return_value=STAGE_CREATED,
    )
    def test_progress_for_created_stage(self, _mock_stage, _mock_flags):
        movement = _movement()
        self.assertEqual(policy.movement_progress_percentage(movement), 10)

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_execution_stage',
        return_value=STAGE_IN_TRANSIT,
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': True,
            'in_transit_done': True,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    def test_progress_uses_milestone_flags(self, _mock_flags, _mock_stage):
        movement = _movement(status=TenantTruckMovementLog.Status.IN_PROGRESS)
        self.assertGreaterEqual(
            policy.movement_progress_percentage(movement),
            policy._STAGE_PROGRESS[STAGE_IN_TRANSIT],
        )


class MovementProjectionTests(SimpleTestCase):
    @patch(
        'mobile_api.dashboard.projections.movement_projection.build_movement_location_block',
        return_value={
            'pickup_address': {
                'location_id': 'loc-from',
                'display_name': 'Goa',
                'label': 'Goa',
            },
            'drop_address': {
                'location_id': 'loc-to',
                'display_name': 'delhi',
                'label': 'delhi',
            },
        },
    )
    def test_build_empty_move_card_from_selection(self, _mock_loc):
        movement = _movement()
        selection = DriverEmptyMoveSelectionResult(
            movement=movement,
            movement_stage=STAGE_CREATED,
            movement_status=TenantTruckMovementLog.Status.SCHEDULED,
            progress_percentage=10,
        )
        card = build_empty_move_card(selection=selection)
        self.assertEqual(card['movement_no'], 'EM-1')
        self.assertEqual(card['movement_id'], str(movement.movement_id))
        self.assertEqual(card['job_id'], card['movement_id'])
        self.assertEqual(card['movement_stage'], STAGE_CREATED)
        self.assertEqual(card['progress_percentage'], 10)
        self.assertEqual(card['pickup_address']['display_name'], 'Goa')
        self.assertEqual(card['drop_address']['display_name'], 'delhi')

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_operational_stage',
        return_value='Created',
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_execution_stage',
        return_value=STAGE_CREATED,
    )
    def test_build_movement_summary_includes_operational_fields(
        self, _mock_stage, _mock_op, _mock_flags
    ):
        movement = _movement()
        summary = build_movement_summary(movement)
        self.assertTrue(summary.get('is_empty_move'))
        self.assertEqual(summary['movement_no'], 'EM-1')


class DashboardMovementSelectorTests(SimpleTestCase):
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_operational_stage',
        return_value='Created',
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_execution_stage',
        return_value=STAGE_CREATED,
    )
    @patch(
        'mobile_api.dashboard.selectors.dashboard_movement_selector.TenantTruckMovementLog'
    )
    def test_selects_active_empty_move(
        self, mock_model, _mock_stage, _mock_flags, _mock_op
    ):
        driver = _driver()
        movement = _movement(
            driver_id=driver.pk,
            status=TenantTruckMovementLog.Status.IN_PROGRESS,
        )
        mock_model.objects.filter.return_value = _mock_movement_queryset([movement])

        result = DashboardMovementSelector().select_current_empty_move(driver)
        self.assertIsNotNone(result)
        self.assertEqual(result.movement, movement)

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_operational_stage',
        return_value='Created',
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_execution_stage',
        return_value=STAGE_CREATED,
    )
    @patch(
        'mobile_api.dashboard.selectors.dashboard_movement_selector.TenantTruckMovementLog'
    )
    def test_select_skips_completed_in_python_gate(
        self, mock_model, _mock_stage, _mock_flags, _mock_op
    ):
        driver = _driver()
        done = _movement(
            driver_id=driver.pk,
            status=TenantTruckMovementLog.Status.COMPLETED,
        )
        active = _movement(
            driver_id=driver.pk,
            status=TenantTruckMovementLog.Status.SCHEDULED,
            movement_no='EM-ACTIVE',
        )
        mock_model.objects.filter.return_value = _mock_movement_queryset(
            [done, active]
        )

        result = select_current_driver_empty_move(driver)
        self.assertEqual(result.movement.movement_no, 'EM-ACTIVE')

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_operational_stage',
        return_value='Created',
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_execution_stage',
        return_value=STAGE_CREATED,
    )
    @patch(
        'mobile_api.dashboard.selectors.dashboard_movement_selector.TenantTruckMovementLog'
    )
    def test_select_excludes_loaded_shipment_row(
        self, mock_model, _mock_stage, _mock_flags, _mock_op
    ):
        driver = _driver()
        loaded = _movement(
            movement_source='Loaded',
            empty_move_reason='',
            shipment_id=uuid4(),
            driver_id=driver.pk,
        )
        empty = _movement(driver_id=driver.pk, movement_no='EM-ONLY')
        mock_model.objects.filter.return_value = _mock_movement_queryset(
            [loaded, empty]
        )

        result = DashboardMovementSelector().select_current_empty_move(driver)
        self.assertEqual(result.movement.movement_no, 'EM-ONLY')

    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_operational_stage',
        return_value='Created',
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.movement_log_milestone_flags',
        return_value={
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        },
    )
    @patch(
        'mobile_api.dashboard.selectors.movement_selection_policy.derive_movement_execution_stage',
        return_value=STAGE_CREATED,
    )
    @patch(
        'mobile_api.dashboard.selectors.dashboard_movement_selector.TenantTruckMovementLog'
    )
    def test_exclude_booking_id_skips_linked_empty_move(
        self, mock_model, _mock_stage, _mock_flags, _mock_op
    ):
        driver = _driver()
        booking_id = uuid4()
        linked = _movement(
            driver_id=driver.pk,
            booking_id=booking_id,
            movement_no='EM-LINKED',
        )
        other = _movement(driver_id=driver.pk, movement_no='EM-OTHER')
        mock_model.objects.filter.return_value = _mock_movement_queryset(
            [linked, other]
        )

        result = DashboardMovementSelector().select_current_empty_move(
            driver,
            exclude_booking_id=booking_id,
        )
        self.assertEqual(result.movement.movement_no, 'EM-OTHER')

    def test_projection_service_select_and_project(self):
        driver = _driver()
        movement = _movement(driver_id=driver.pk)
        selector = MagicMock()
        selection = DriverEmptyMoveSelectionResult(
            movement=movement,
            movement_stage=STAGE_CREATED,
            movement_status=TenantTruckMovementLog.Status.SCHEDULED,
            progress_percentage=10,
            summary={'movement_no': 'EM-1'},
        )
        selector.select_current_empty_move.return_value = selection
        service = MovementProjectionService(selector=selector)

        sel, card, summary = service.select_and_project_empty_move(driver)
        self.assertIs(sel, selection)
        self.assertEqual(card['movement_no'], 'EM-1')
        self.assertEqual(summary['movement_no'], 'EM-1')
