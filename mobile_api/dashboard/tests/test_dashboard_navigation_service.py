"""Tests for dashboard empty-move resume navigation."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.dashboard.dto.driver_dashboard_context import DriverDashboardContext
from mobile_api.dashboard.services.dashboard_navigation_service import (
    build_dashboard_next_action_hint,
    build_dashboard_on_call_state,
)
from tenant_workspace.models import TenantTruckMovementLog


def _movement(*, status=TenantTruckMovementLog.Status.SCHEDULED):
    pk = uuid4()
    return SimpleNamespace(
        pk=pk,
        movement_id=pk,
        movement_no='EM-42',
        status=status,
        movement_source='empty',
        empty_move_reason='reposition',
        shipment_id=None,
        driver_id=uuid4(),
    )


class DashboardNavigationServiceTests(SimpleTestCase):
    def test_on_call_active_empty_move_blocks_create(self):
        movement = _movement()
        ctx = DriverDashboardContext(
            driver=SimpleNamespace(pk=uuid4()),
            tenant_schema='tenant_a',
            user_id=str(uuid4()),
            active_empty_movement=movement,
        )
        on_call = build_dashboard_on_call_state(ctx)
        self.assertTrue(on_call['empty_move_active'])
        self.assertFalse(on_call['can_create_empty_move'])
        self.assertEqual(on_call['job_id'], str(movement.pk))
        self.assertEqual(on_call['resume_job']['job_no'], 'EM-42')

    def test_on_call_idle_driver_may_create(self):
        ctx = DriverDashboardContext(
            driver=SimpleNamespace(pk=uuid4()),
            tenant_schema='tenant_a',
            user_id=str(uuid4()),
        )
        on_call = build_dashboard_on_call_state(ctx)
        self.assertFalse(on_call['empty_move_active'])
        self.assertTrue(on_call['can_create_empty_move'])

    def test_on_call_after_end_job_allows_new_create(self):
        """End Job closes the movement — dashboard must not block a new empty move."""
        movement = _movement(status=TenantTruckMovementLog.Status.COMPLETED)
        ctx = DriverDashboardContext(
            driver=SimpleNamespace(pk=uuid4()),
            tenant_schema='tenant_a',
            user_id=str(uuid4()),
            active_empty_movement=movement,
        )
        on_call = build_dashboard_on_call_state(ctx)
        self.assertFalse(on_call['empty_move_active'])
        self.assertTrue(on_call['can_create_empty_move'])

    def test_next_action_hint_empty_after_end_job(self):
        movement = _movement(status=TenantTruckMovementLog.Status.COMPLETED)
        ctx = DriverDashboardContext(
            driver=SimpleNamespace(pk=uuid4()),
            tenant_schema='tenant_a',
            user_id=str(uuid4()),
            active_empty_movement=movement,
        )
        self.assertEqual(
            build_dashboard_next_action_hint(ctx, workflow={'allowed_actions': []}),
            {},
        )

    @patch('mobile_api.dashboard.services.dashboard_navigation_service.build_next_action_hint')
    @patch(
        'mobile_api.dashboard.services.dashboard_navigation_service.align_next_action_hint_with_workflow',
        side_effect=lambda hint, *a, **k: hint,
    )
    def test_next_action_hint_includes_resume_pointer(self, _align, mock_build):
        movement = _movement()
        mock_build.return_value = {
            'action': 'go_to_evidence_capture',
            'screen': 'evidence_capture',
            'action_code': 'OA-0014',
        }
        ctx = DriverDashboardContext(
            driver=SimpleNamespace(pk=uuid4()),
            tenant_schema='tenant_a',
            user_id=str(uuid4()),
            active_empty_movement=movement,
            pod_cod_projection={},
        )
        hint = build_dashboard_next_action_hint(
            ctx,
            workflow={'next_action': {'action_code': 'OA-0014'}},
        )
        self.assertEqual(hint['job_type'], 'movement')
        self.assertEqual(hint['job_id'], str(movement.pk))
        self.assertTrue(hint['resume_existing_movement'])

    def test_next_action_hint_empty_without_movement(self):
        ctx = DriverDashboardContext(
            driver=SimpleNamespace(pk=uuid4()),
            tenant_schema='tenant_a',
            user_id=str(uuid4()),
        )
        self.assertEqual(
            build_dashboard_next_action_hint(ctx, workflow={}),
            {},
        )
