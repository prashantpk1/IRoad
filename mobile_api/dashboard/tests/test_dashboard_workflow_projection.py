"""
Unit tests for dashboard workflow projection (read-only, engine-delegated).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.dto.driver_empty_move_selection import (
    DriverEmptyMoveSelectionResult,
)
from mobile_api.dashboard.selectors import booking_selection_policy as policy
from mobile_api.dashboard.projections.workflow_projection import (
    build_empty_move_workflow,
    build_shipment_workflow,
    build_workflow_for_dashboard_context,
    build_workflow_projection,
)
from mobile_api.dashboard.services.dashboard_summary_service import (
    DashboardSummaryService,
)
from tenant_workspace.models import TenantTruckMovementLog


def _action_row(code='A1', label='Start'):
    return {
        'action_id': str(uuid4()),
        'action_code': code,
        'action_name': label,
        'execution_label': label,
        'requires_gps': True,
        'requires_photo': False,
        'requires_video': False,
        'requires_note': False,
        'action_category': 'job',
        'execution_order': 1,
        'sort_index': 0,
        'current_stage': 'Pickup',
        'execution_requirements': {'gps': True, 'photo': False},
    }


def _engine_payload(*, actions=None, stage='Pickup', job_type='shipment'):
    rows = actions if actions is not None else [_action_row()]
    primary = rows[0] if rows else None
    return {
        'job_type': job_type,
        'job_id': str(uuid4()),
        'job_no': 'JOB-1',
        'current_stage': stage,
        'context_label': 'test context',
        'count': len(rows),
        'actions': rows,
        'primary_action': primary,
        'workflow_source': 'operation_execution.get_allowed_actions',
    }


def _shipment(*, status='Loaded', line='Outbound'):
    s = MagicMock()
    s.pk = uuid4()
    s.shipment_id = s.pk
    s.shipment_no = 'SH-100'
    s.shipment_status = status
    s.booking_item_type = line
    return s


def _movement(*, status=TenantTruckMovementLog.Status.SCHEDULED):
    m = MagicMock()
    m.pk = uuid4()
    m.movement_id = m.pk
    m.movement_no = 'EM-50'
    m.status = status
    m.movement_source = 'empty'
    return m


def _booking():
    b = MagicMock()
    b.pk = uuid4()
    b.booking_id = b.pk
    b.booking_no = 'BK-10'
    return b


class WorkflowProjectionTests(SimpleTestCase):
    @patch(
        'mobile_api.dashboard.projections.workflow_projection.derive_job_execution_stage',
    )
    @patch(
        'mobile_api.dashboard.projections.workflow_projection.OperationExecutionService.get_allowed_driver_actions',
    )
    def test_shipment_workflow_maps_engine_output(
        self, mock_allowed, mock_stage
    ):
        mock_allowed.return_value = _engine_payload(stage='Pickup')
        mock_stage.return_value = {
            'entity_type': 'shipment',
            'execution_sub_stage': 'pickup',
            'operational_stage': 'Pickup',
            'status_for_workflow': 'Loaded',
        }
        shipment = _shipment()
        booking = _booking()

        workflow = build_shipment_workflow(
            shipment,
            booking=booking,
            booking_item_type='Outbound',
        )

        self.assertEqual(workflow['current_stage'], 'Pickup')
        self.assertEqual(workflow['workflow_source'], 'operation_execution.get_allowed_actions')
        self.assertEqual(len(workflow['allowed_actions']), 1)
        self.assertEqual(workflow['primary_action']['action_code'], 'A1')
        self.assertEqual(workflow['next_action']['action_code'], 'A1')
        mock_allowed.assert_called_once()
        call_kw = mock_allowed.call_args.kwargs
        self.assertIs(call_kw['shipment'], shipment)
        self.assertIs(call_kw['booking'], booking)
        self.assertEqual(call_kw['booking_item_type'], 'Outbound')
        self.assertIsNone(call_kw['movement'])

    @patch(
        'mobile_api.dashboard.projections.workflow_projection.derive_job_execution_stage',
    )
    @patch(
        'mobile_api.dashboard.projections.workflow_projection.OperationExecutionService.get_allowed_driver_actions',
    )
    def test_empty_move_workflow(self, mock_allowed, mock_stage):
        mock_allowed.return_value = _engine_payload(
            actions=[_action_row('EM1', 'Start Movement')],
            stage='Created',
            job_type='movement',
        )
        mock_stage.return_value = {
            'entity_type': 'movement',
            'execution_sub_stage': 'created',
            'operational_stage': 'Created',
            'status_for_workflow': 'Scheduled',
        }
        movement = _movement()

        workflow = build_empty_move_workflow(movement)

        self.assertEqual(workflow['current_stage'], 'Created')
        self.assertEqual(workflow['workflow_metadata']['entity_type'], 'movement')
        call_kw = mock_allowed.call_args.kwargs
        self.assertIs(call_kw['movement'], movement)
        self.assertIsNone(call_kw['shipment'])

    @patch(
        'mobile_api.dashboard.projections.workflow_projection.derive_job_execution_stage',
    )
    @patch(
        'mobile_api.dashboard.projections.workflow_projection.OperationExecutionService.get_allowed_driver_actions',
    )
    def test_stage_derivation_fallback_from_stage_block(
        self, mock_allowed, mock_stage
    ):
        mock_allowed.return_value = _engine_payload(stage='')
        mock_stage.return_value = {
            'entity_type': 'shipment',
            'execution_sub_stage': 'loading',
            'operational_stage': 'Loading',
            'status_for_workflow': 'Loaded',
        }
        workflow = build_shipment_workflow(_shipment())
        self.assertEqual(workflow['current_stage'], 'Loading')

    @patch(
        'mobile_api.dashboard.projections.workflow_projection.derive_job_execution_stage',
    )
    @patch(
        'mobile_api.dashboard.projections.workflow_projection.OperationExecutionService.get_allowed_driver_actions',
    )
    def test_blocked_actions_empty_allowed_list(self, mock_allowed, mock_stage):
        mock_allowed.return_value = _engine_payload(actions=[], stage='Completed')
        mock_stage.return_value = {
            'entity_type': 'shipment',
            'execution_sub_stage': 'completion',
            'operational_stage': 'Completed',
            'status_for_workflow': 'Closed',
        }
        workflow = build_shipment_workflow(_shipment(status='Closed'))
        self.assertEqual(workflow['allowed_actions'], [])
        self.assertEqual(workflow['primary_action'], {})
        self.assertEqual(workflow['next_action'], {})

    @patch(
        'mobile_api.dashboard.projections.workflow_projection.derive_job_execution_stage',
    )
    @patch(
        'mobile_api.dashboard.projections.workflow_projection.OperationExecutionService.get_allowed_driver_actions',
    )
    def test_next_action_is_primary_action(self, mock_allowed, mock_stage):
        rows = [
            _action_row('A1', 'First'),
            _action_row('A2', 'Second'),
        ]
        payload = _engine_payload(actions=rows)
        payload['primary_action'] = rows[0]
        mock_allowed.return_value = payload
        mock_stage.return_value = {
            'entity_type': 'shipment',
            'execution_sub_stage': 'pickup',
            'operational_stage': 'Pickup',
            'status_for_workflow': 'Loaded',
        }
        workflow = build_shipment_workflow(_shipment())
        self.assertEqual(workflow['next_action']['action_code'], 'A1')
        self.assertEqual(len(workflow['allowed_actions']), 2)

    @patch(
        'mobile_api.dashboard.projections.workflow_projection.build_shipment_workflow',
    )
    @patch(
        'mobile_api.dashboard.projections.workflow_projection.build_empty_move_workflow',
    )
    def test_context_prefers_shipment_over_empty_move(
        self, mock_empty, mock_shipment
    ):
        mock_shipment.return_value = {'current_stage': 'Pickup'}
        mock_empty.return_value = {'current_stage': 'Created'}
        shipment = _shipment()
        movement = _movement()
        context = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='tenant_a',
            user_id='u1',
            active_shipment=shipment,
            active_empty_movement=movement,
        )
        workflow = build_workflow_for_dashboard_context(context)
        self.assertEqual(workflow['current_stage'], 'Pickup')
        mock_shipment.assert_called_once()
        mock_empty.assert_not_called()

    @patch(
        'mobile_api.dashboard.projections.workflow_projection.build_empty_move_workflow',
    )
    @patch(
        'mobile_api.dashboard.projections.workflow_projection.build_booking_workflow',
    )
    def test_context_uses_booking_workflow_when_no_shipment(
        self, mock_booking_wf, mock_empty
    ):
        mock_booking_wf.return_value = {'current_stage': 'Planned', 'allowed_actions': []}
        booking = _booking()
        context = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='tenant_a',
            user_id='u1',
            active_booking=booking,
            booking_selection=DriverBookingSelectionResult(
                booking=booking,
                active_shipment=None,
                next_executable_shipment=None,
                booking_execution_stage=policy.BOOKING_EXECUTION_STAGE_NOT_STARTED,
            ),
        )
        workflow = build_workflow_for_dashboard_context(context)
        self.assertEqual(workflow['current_stage'], 'Planned')
        mock_booking_wf.assert_called_once()
        mock_empty.assert_not_called()

    def test_empty_projection_without_entity(self):
        workflow = build_workflow_projection()
        self.assertEqual(workflow['allowed_actions'], [])
        self.assertEqual(workflow['workflow_source'], '')


class DashboardSummaryServiceWorkflowTests(SimpleTestCase):
    @patch.object(DashboardSummaryService, 'build_timeline_summary')
    @patch.object(DashboardSummaryService, 'build_alerts')
    def test_build_summary_includes_timeline_and_alerts(
        self, mock_alerts, mock_timeline
    ):
        mock_timeline.return_value = {'scope': 'shipment', 'recent_count': 0}
        mock_alerts.return_value = {'count': 0, 'items': []}
        context = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='t',
            user_id='1',
        )
        summary = DashboardSummaryService().build_summary(context)
        self.assertIn('timeline_summary', summary)
        self.assertIn('alerts', summary)

    @patch(
        'mobile_api.dashboard.services.dashboard_summary_service.build_workflow_from_booking_selection',
    )
    def test_build_workflow_for_job(self, mock_build):
        mock_build.return_value = {'current_stage': 'In Transit'}
        booking = _booking()
        shipment = _shipment()
        selection = DriverBookingSelectionResult(
            booking=booking,
            active_shipment=shipment,
            next_executable_shipment=shipment,
        )
        workflow = DashboardSummaryService().build_workflow_for_job(selection)
        self.assertEqual(workflow['current_stage'], 'In Transit')
        mock_build.assert_called_once()

    @patch(
        'mobile_api.dashboard.services.dashboard_summary_service.build_workflow_from_empty_move_selection',
    )
    def test_build_workflow_for_empty_move(self, mock_build):
        mock_build.return_value = {'current_stage': 'Started'}
        selection = DriverEmptyMoveSelectionResult(movement=_movement())
        workflow = DashboardSummaryService().build_workflow_for_empty_move(selection)
        self.assertEqual(workflow['current_stage'], 'Started')

    @patch.object(DashboardSummaryService, 'build_workflow')
    def test_populate_context_workflow(self, mock_workflow):
        mock_workflow.return_value = {'current_stage': 'Pickup'}
        context = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='t',
            user_id='1',
        )
        DashboardSummaryService().populate_context_workflow(context)
        self.assertEqual(context.workflow_projection['current_stage'], 'Pickup')
