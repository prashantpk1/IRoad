"""Hard POD workflow overlay tests."""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.job_detail.services.hard_pod_workflow_overlay import (
    apply_hard_pod_workflow_overlay,
    enrich_pod_cod_hard_copy_gate,
)


class HardPodWorkflowOverlayTests(SimpleTestCase):
    def test_overrides_primary_when_hard_copy_due(self):
        workflow = apply_hard_pod_workflow_overlay(
            {
                'primary_action': {
                    'action_code': 'A9',
                    'execution_label': 'Collect Payment',
                },
                'next_action': {'action_code': 'A9'},
                'allowed_actions': [
                    {
                        'action_code': 'OA-0009',
                        'execution_label': 'Collect Payment',
                        'execution_requirements': {'auto_treasury_post': True},
                    },
                    {'action_code': 'OA-0010', 'execution_label': 'Job Closed'},
                ],
            },
            {
                'hard_pod_pending': True,
                'pod_pending': False,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
                    'execute_action_code': 'OA-0015',
                },
            },
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'OA-0015')
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
        self.assertEqual(len(workflow['allowed_actions']), 1)
        self.assertEqual(
            workflow['allowed_actions'][0]['action'],
            'go_to_pod_capture',
        )
        self.assertTrue(workflow['workflow_metadata']['payment_collection_blocked'])

    def test_overrides_primary_when_hard_copy_due_legacy_fallback(self):
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
            {'hard_pod_pending': True, 'pod_pending': True, 'pod_type': 'Hard'},
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'A7')

    def test_enrich_pod_cod_sets_payment_block_while_hard_copy_due(self):
        pod = enrich_pod_cod_hard_copy_gate(
            {
                'hard_pod_pending': True,
                'pod_pending': False,
                'hard_copy_confirmation': {'required': True, 'pending': True},
            },
        )
        self.assertTrue(pod['payment_collection_blocked'])
        self.assertTrue(pod['digital_pod_complete'])
        self.assertIn('hard-copy', pod['payment_collection_block_reason'].casefold())

    def test_enrich_pod_cod_clears_payment_block_when_hard_copy_done(self):
        pod = enrich_pod_cod_hard_copy_gate(
            {
                'hard_pod_pending': False,
                'pod_pending': False,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': False,
                    'confirmation_ui': {'ui_mode': 'hard_pod_collection_confirmation'},
                },
            },
        )
        self.assertFalse(pod['payment_collection_blocked'])
        self.assertNotIn('confirmation_ui', pod['hard_copy_confirmation'])

    def test_finalize_pod_cod_strips_active_hard_copy_ui(self):
        from mobile_api.job_detail.services.hard_pod_workflow_overlay import (
            finalize_pod_cod_hard_copy_navigation,
        )

        pod = finalize_pod_cod_hard_copy_navigation(
            {
                'hard_pod_pending': False,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': False,
                    'confirmation_ui': {'ui_mode': 'hard_pod_collection_confirmation'},
                    'ui_mode': 'hard_pod_collection_confirmation',
                },
            },
        )
        block = pod['hard_copy_confirmation']
        self.assertFalse(block.get('actionable'))
        self.assertNotIn('confirmation_ui', block)
        self.assertEqual(block.get('ui_mode'), '')

    def test_overlay_when_hard_pod_pending_even_if_block_pending_false(self):
        workflow = apply_hard_pod_workflow_overlay(
            {
                'primary_action': {
                    'action_code': 'OA-0010',
                    'execution_label': 'Job Closed',
                },
                'allowed_actions': [
                    {'action_code': 'OA-0010', 'execution_label': 'Job Closed'},
                ],
            },
            {
                'hard_pod_pending': True,
                'pod_pending': False,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': False,
                    'execute_action_code': 'OA-0008',
                },
            },
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'OA-0008')
        self.assertEqual(workflow['primary_action']['capture_mode'], 'hard_copy_confirmation')
        self.assertNotIn(
            'OA-0010',
            [row.get('action_code') for row in workflow.get('allowed_actions') or []],
        )
