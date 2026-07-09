"""Tests for empty-move workflow_status ↔ timeline_preview sync."""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.job_detail.projections.movement_workflow_timeline_sync import (
    attach_timeline_preview_to_workflow,
    sync_workflow_status_to_timeline_preview,
)


class MovementWorkflowTimelineSyncTests(SimpleTestCase):
    def test_sync_marks_arrival_performed_when_workflow_status_completed(self):
        workflow_status = [
            {'step_key': 'pickup', 'action_code': 'EM1', 'completed': True, 'is_performed': True},
            {'step_key': 'in_transit', 'action_code': 'EM2', 'completed': True, 'is_performed': True},
            {
                'step_key': 'delivery',
                'action_code': 'OA-EM-003',
                'completed': True,
                'is_performed': True,
                'display_timestamp': '2026-06-25 14:00',
            },
            {'step_key': 'complete', 'action_code': 'EM4', 'completed': False, 'is_performed': False},
        ]
        timeline_preview = [
            {'action_code': 'EM1', 'is_performed': True, 'timeline_state': 'performed'},
            {'action_code': 'EM2', 'is_performed': True, 'timeline_state': 'performed'},
            {
                'action_code': 'OA-EM-003',
                'is_performed': False,
                'timeline_state': 'pending',
            },
            {'action_code': 'EM4', 'is_performed': False, 'timeline_state': 'pending'},
        ]
        synced = sync_workflow_status_to_timeline_preview(
            workflow_status,
            timeline_preview,
        )
        self.assertTrue(synced[2]['is_performed'])
        self.assertTrue(synced[2]['completed'])
        self.assertEqual(synced[2]['timeline_state'], 'performed')
        self.assertEqual(synced[2]['display_timestamp'], '2026-06-25 14:00')
        self.assertEqual(synced[2]['step_key'], 'delivery')

    def test_attach_timeline_preview_to_workflow_for_movement(self):
        workflow = {
            'workflow_status': [
                {
                    'step_key': 'delivery',
                    'action_code': 'EM3',
                    'completed': True,
                    'is_performed': True,
                },
            ],
        }
        timeline = {
            'timeline_preview': [
                {'action_code': 'EM3', 'is_performed': False, 'timeline_state': 'pending'},
            ],
        }
        out = attach_timeline_preview_to_workflow(
            workflow,
            timeline,
            job_type='movement',
        )
        self.assertTrue(out['timeline_preview'][0]['is_performed'])
        self.assertEqual(out['timeline_step_count'], 1)
