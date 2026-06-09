"""Hard POD workflow overlay tests."""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.job_detail.services.hard_pod_workflow_overlay import (
    apply_hard_pod_workflow_overlay,
)


class HardPodWorkflowOverlayTests(SimpleTestCase):
    def test_overrides_primary_when_hard_copy_due(self):
        workflow = apply_hard_pod_workflow_overlay(
            {
                'primary_action': {
                    'action_code': 'A8',
                    'execution_label': 'Unloading Completed',
                },
                'next_action': {'action_code': 'A8'},
            },
            {
                'hard_pod_pending': True,
                'pod_pending': False,
                'hard_copy_confirmation': {'required': True, 'pending': True},
            },
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'A7H')
        self.assertEqual(workflow['primary_action']['action'], 'go_to_pod_capture')
        self.assertEqual(workflow['primary_action']['capture_mode'], 'hard_copy_confirmation')
        self.assertEqual(
            workflow['primary_action']['screen_title'],
            'Hard POD Collection Confirmation',
        )
        self.assertEqual(
            workflow['primary_action']['ui_mode'],
            'hard_pod_collection_confirmation',
        )

    def test_no_overlay_when_digital_pod_still_pending(self):
        workflow = apply_hard_pod_workflow_overlay(
            {'primary_action': {'action_code': 'A7'}},
            {'hard_pod_pending': True, 'pod_pending': True},
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'A7')
