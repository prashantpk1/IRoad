"""Tests for empty-move workflow_status projection."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from mobile_api.job_detail.projections.movement_workflow_status_projection import (
    build_movement_workflow_status,
)


def _movement():
    return SimpleNamespace(
        movement_id=uuid.uuid4(),
        pk=uuid.uuid4(),
        movement_no='TML-0999',
        from_location_point=None,
        to_location_point=None,
        from_location_address='Pickup addr',
        to_location_address='Drop addr',
    )


def _log(action_code: str):
    impacts = {
        'EM1': 'In_Progress',
        'EM4': 'Completed',
    }
    action = SimpleNamespace(
        action_code=action_code,
        english_label=action_code,
        arabic_label=action_code,
        movement_status_impact=impacts.get(action_code, ''),
        shipment_status_impact='',
    )
    return SimpleNamespace(
        log_id=uuid.uuid4(),
        operation_action=action,
        log_date=None,
        created_at=None,
        media_rows=MagicMock(all=MagicMock(return_value=[])),
    )


class MovementWorkflowStatusProjectionTests(SimpleTestCase):
    def test_steps_not_completed_without_logs(self):
        steps = build_movement_workflow_status(_movement(), [])
        self.assertEqual(len(steps), 3)
        self.assertFalse(steps[0]['completed'])
        self.assertEqual(steps[0]['step_key'], 'pickup')

    def test_pickup_complete_only_after_em1(self):
        steps = build_movement_workflow_status(_movement(), [_log('EM1')])
        self.assertTrue(steps[0]['completed'])
        self.assertFalse(steps[1]['completed'])
        self.assertFalse(steps[2]['completed'])

    def test_delivery_complete_after_em3(self):
        logs = [_log('EM1'), _log('EM2'), _log('EM3')]
        steps = build_movement_workflow_status(_movement(), logs)
        self.assertTrue(steps[0]['completed'])
        self.assertTrue(steps[1]['completed'])
        self.assertTrue(steps[2]['completed'])

    def test_delivery_complete_when_em4_done_without_em3_log(self):
        logs = [_log('EM1'), _log('EM2'), _log('EM4')]
        steps = build_movement_workflow_status(_movement(), logs)
        self.assertTrue(steps[2]['completed'])
        self.assertEqual(steps[2]['step_key'], 'delivery')
        self.assertTrue(any(step.get('step_key') == 'complete' for step in steps))

    def test_delivery_complete_from_arrival_label_without_em_code(self):
        action = SimpleNamespace(
            action_code='M3',
            english_label='Arrival At Destination',
            arabic_label='Arrival At Destination',
            movement_status_impact='',
            shipment_status_impact='',
        )
        logs = [_log('EM1'), _log('EM2'), SimpleNamespace(
            log_id=uuid.uuid4(),
            operation_action=action,
            log_date=None,
            created_at=None,
            media_rows=MagicMock(all=MagicMock(return_value=[])),
        )]
        steps = build_movement_workflow_status(_movement(), logs)
        self.assertTrue(steps[2]['completed'])
