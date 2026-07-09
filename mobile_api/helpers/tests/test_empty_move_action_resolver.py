"""Dynamic empty-move Action Master resolution for mobile."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.helpers.empty_move_action_resolver import (
    action_is_empty_move_lifecycle,
    resolve_empty_move_start_action_code,
    resolve_empty_move_workflow_step_specs,
    row_is_empty_move_action,
)
from tenant_workspace.models import TenantTruckMovementLog


class EmptyMoveActionResolverTests(SimpleTestCase):
    def test_row_is_empty_move_action_by_category(self):
        self.assertTrue(
            row_is_empty_move_action(
                {
                    'action_code': 'OA-EM-001',
                    'execution_requirements': {'sequence_category': 'empty_move'},
                },
            ),
        )

    def test_action_is_empty_move_lifecycle_by_impact(self):
        action = SimpleNamespace(
            action_code='OA-EM-001',
            english_label='Start Movement',
            sequence_category='empty_move',
            movement_status_impact=TenantTruckMovementLog.Status.IN_PROGRESS,
            shipment_status_impact='',
        )
        self.assertTrue(action_is_empty_move_lifecycle(action))

    @patch('mobile_api.helpers.empty_move_action_resolver._iter_empty_move_actions')
    def test_resolve_start_action_code_from_tenant_row(self, mock_iter):
        mock_iter.return_value = [
            SimpleNamespace(
                action_code='OA-EM-001',
                english_label='Start Movement',
                sequence_category='empty_move',
                movement_status_impact='In_Progress',
                shipment_status_impact='',
                sequence_number=1,
            ),
        ]
        self.assertEqual(
            resolve_empty_move_start_action_code('tenant_a'),
            'OA-EM-001',
        )

    @patch('mobile_api.helpers.empty_move_action_resolver._iter_empty_move_actions')
    def test_workflow_step_specs_use_tenant_codes(self, mock_iter):
        mock_iter.return_value = [
            SimpleNamespace(
                action_code='OA-EM-001',
                english_label='Start Movement',
                sequence_category='empty_move',
                movement_status_impact='In_Progress',
                shipment_status_impact='',
                sequence_number=1,
            ),
            SimpleNamespace(
                action_code='OA-EM-002',
                english_label='Depart Empty',
                sequence_category='empty_move',
                movement_status_impact='',
                shipment_status_impact='',
                sequence_number=2,
            ),
            SimpleNamespace(
                action_code='OA-EM-003',
                english_label='Arrival At Destination',
                sequence_category='empty_move',
                movement_status_impact='',
                shipment_status_impact='',
                sequence_number=3,
            ),
            SimpleNamespace(
                action_code='OA-EM-004',
                english_label='Complete Movement',
                sequence_category='empty_move',
                movement_status_impact='Completed',
                shipment_status_impact='',
                sequence_number=4,
            ),
        ]
        specs = resolve_empty_move_workflow_step_specs('tenant_a')
        self.assertEqual(len(specs), 4)
        self.assertEqual(specs[0][2], ('OA-EM-001',))
        self.assertEqual(specs[1][2], ('OA-EM-002',))
        self.assertEqual(specs[2][2], ('OA-EM-003',))
        self.assertEqual(specs[0][1], 'Start Movement')
        self.assertEqual(specs[1][1], 'Depart Empty')
        self.assertEqual(specs[2][1], 'Arrival At Destination')

    def test_workflow_step_specs_fallback_without_schema(self):
        specs = resolve_empty_move_workflow_step_specs('')
        self.assertEqual(len(specs), 4)
        self.assertEqual(specs[0][2], ('EM1',))
        self.assertEqual(specs[3][2], ('EM4',))
        self.assertEqual(specs[0][0], 'pickup')
        self.assertEqual(specs[3][0], 'complete')

    @patch('mobile_api.helpers.empty_move_action_resolver._iter_empty_move_actions')
    def test_three_step_tenant_config_oa_codes(self, mock_iter):
        mock_iter.return_value = [
            SimpleNamespace(
                action_code='OA-0014',
                english_label='Start Job',
                sequence_category='empty_move',
                sequence_number=1,
            ),
            SimpleNamespace(
                action_code='OA-0015',
                english_label='Departure',
                sequence_category='empty_move',
                sequence_number=2,
            ),
            SimpleNamespace(
                action_code='OA-0016',
                english_label='End Job',
                sequence_category='empty_move',
                movement_status_impact='Completed',
                sequence_number=3,
            ),
        ]
        specs = resolve_empty_move_workflow_step_specs('tenant_a')
        self.assertEqual(len(specs), 3)
        self.assertEqual(specs[0], ('seq_1', 'Start Job', ('OA-0014',)))
        self.assertEqual(specs[2], ('seq_3', 'End Job', ('OA-0016',)))
