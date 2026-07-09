"""Tests for hard-copy workflow gate helpers."""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.helpers.hard_copy_workflow_gate import (
    coerce_digital_pod_capture_row,
    derive_unloading_pending,
    hard_copy_step_due,
    hard_copy_workflow_gate_open,
    scrub_premature_hard_pod_job_detail_payload,
)
from mobile_api.job_detail.services.hard_pod_workflow_overlay import (
    apply_hard_pod_workflow_overlay,
)


class HardCopyWorkflowGateTests(SimpleTestCase):
    def test_unloading_pending_after_start_unloading_before_completed(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        shipment = SimpleNamespace(shipment_status='At Delivery')
        with patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_delivery_arrival_done',
            return_value=True,
        ), patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_done',
            return_value=True,
        ), patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_completed_done',
            return_value=False,
        ):
            self.assertTrue(derive_unloading_pending(shipment))

    def test_unloading_not_pending_after_unloading_completed(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        shipment = SimpleNamespace(shipment_status='At Delivery')
        with patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_delivery_arrival_done',
            return_value=True,
        ), patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_done',
            return_value=True,
        ), patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_completed_done',
            return_value=True,
        ):
            self.assertFalse(derive_unloading_pending(shipment))

    def test_gate_open_when_digital_log_evidence_present(self):
        pod_cod = {
            'hard_pod_pending': True,
            'pod_pending': True,
            'log_evidence': {'pod_uploaded': True},
            'hard_copy_confirmation': {
                'required': True,
                'applicable': True,
                'actionable': True,
            },
        }
        self.assertTrue(hard_copy_workflow_gate_open(pod_cod))
        self.assertTrue(hard_copy_step_due(pod_cod))

    def test_gate_closed_before_digital_for_combined_wizard(self):
        pod_cod = {
            'hard_pod_pending': True,
            'pod_pending': False,
            'capture_steps': ['digital_evidence', 'hard_copy_confirmation'],
            'hard_copy_confirmation': {'required': True, 'applicable': True},
        }
        self.assertFalse(hard_copy_workflow_gate_open(pod_cod))
        self.assertFalse(hard_copy_step_due(pod_cod))

    def test_gate_closed_while_unloading_pending(self):
        pod_cod = {
            'hard_pod_pending': True,
            'pod_pending': True,
            'unloading_pending': True,
            'hard_copy_confirmation': {'required': True, 'applicable': True},
        }
        self.assertFalse(hard_copy_step_due(pod_cod))

    def test_unloading_done_digital_pending_blocks_hard_copy(self):
        pod_cod = {
            'hard_pod_pending': True,
            'pod_pending': True,
            'unloading_pending': True,
            'hard_copy_confirmation': {'required': True, 'applicable': True},
        }
        self.assertFalse(hard_copy_step_due(pod_cod))

    def test_empty_capture_steps_defaults_digital_first(self):
        pod_cod = {
            'hard_pod_pending': True,
            'pod_pending': False,
            'hard_copy_confirmation': {'required': True, 'applicable': True},
        }
        self.assertFalse(hard_copy_workflow_gate_open(pod_cod))
        self.assertFalse(hard_copy_step_due(pod_cod))

    def test_coerce_hard_copy_row_back_to_digital(self):
        pod_cod = {
            'hard_pod_pending': True,
            'pod_pending': True,
            'capture_steps': ['digital_evidence', 'hard_copy_confirmation'],
            'hard_copy_confirmation': {'required': True, 'applicable': True},
        }
        row = coerce_digital_pod_capture_row(
            {
                'action': 'go_to_pod_capture',
                'capture_mode': 'hard_copy_confirmation',
                'active_step': 'hard_copy_confirmation',
                'confirmation_ui': {'ui_mode': 'hard_pod_collection_confirmation'},
            },
            pod_cod=pod_cod,
        )
        self.assertEqual(row['capture_mode'], 'digital_evidence')
        self.assertEqual(row['active_step'], 'digital_evidence')
        self.assertNotIn('confirmation_ui', row)

    def test_scrub_job_detail_payload_while_unloading_completed_pending(self):
        workflow = {
            'primary_action': {
                'action_code': 'OA-0008',
                'action_name': 'Unloading Completed',
                'action': 'go_to_evidence_capture',
                'screen': 'evidence_capture',
                'requires_evidence_capture': True,
            },
            'allowed_actions': [
                {
                    'action_code': 'OA-0008',
                    'action': 'go_to_evidence_capture',
                    'requires_evidence_capture': True,
                },
                {
                    'action_code': 'OA-0009',
                    'action': 'go_to_pod_capture',
                    'capture_mode': 'digital_evidence',
                    'hard_pod': True,
                    'includes_hard_copy': True,
                    'pod_capture_steps': ['digital_evidence', 'hard_copy_confirmation'],
                    'hard_copy_confirmation': {
                        'applicable': False,
                        'pages': [{'label': 'IMG-(SH-0132-001)'}],
                    },
                    'capture_ui': {
                        'primary_button': {
                            'wizard_next_step': 'hard_copy_confirmation',
                        },
                    },
                    'execution_requirements': {
                        'capture_ui': {
                            'primary_button': {
                                'wizard_next_step': 'hard_copy_confirmation',
                            },
                        },
                    },
                },
            ],
        }
        pod_cod = {
            'hard_pod_pending': True,
            'unloading_pending': True,
            'digital_evidence_complete': False,
            'log_evidence': {'pod_uploaded': False},
            'capture_steps': ['digital_evidence', 'hard_copy_confirmation'],
            'hard_copy_confirmation': {
                'applicable': False,
                'pages': [{'label': 'IMG-(SH-0132-001)'}],
            },
        }
        hint = {
            'action': 'go_to_evidence_capture',
            'screen': 'evidence_capture',
            'action_code': 'OA-0008',
        }
        wf, pod, hint = scrub_premature_hard_pod_job_detail_payload(
            workflow=workflow,
            pod_cod=pod_cod,
            next_hint=hint,
        )
        self.assertFalse(pod['hard_pod_pending'])
        self.assertEqual(pod['hard_copy_confirmation']['pages'], [])
        self.assertFalse(hint.get('hard_pod_capture_due'))
        pod_row = wf['allowed_actions'][1]
        self.assertFalse(pod_row.get('hard_pod'))
        self.assertNotIn('wizard_next_step', (pod_row.get('capture_ui') or {}).get('primary_button', {}))
        req_ui = (pod_row.get('execution_requirements') or {}).get('capture_ui') or {}
        self.assertNotIn('wizard_next_step', req_ui.get('primary_button', {}))
        self.assertEqual(pod_row['hard_copy_confirmation']['pages'], [])

    def test_scrub_clears_hard_pod_when_digital_done_without_portal_document(self):
        workflow = {'allowed_actions': [], 'primary_action': {}}
        pod_cod = {
            'hard_pod_pending': True,
            'log_evidence': {'pod_uploaded': True},
            'capture_steps': ['digital_evidence', 'hard_copy_confirmation'],
            'hard_copy_confirmation': {
                'applicable': False,
                'actionable': False,
                'pending': True,
                'pages': [{'label': 'IMG-(SH-0132-001)'}],
            },
        }
        hint = {'action': 'refresh_job_detail', 'screen': 'job_detail'}
        _wf, pod, _hint = scrub_premature_hard_pod_job_detail_payload(
            workflow=workflow,
            pod_cod=pod_cod,
            next_hint=hint,
        )
        self.assertFalse(pod['hard_pod_pending'])
        self.assertEqual(pod['hard_copy_confirmation']['pages'], [])

    def test_overlay_when_digital_done_but_pod_column_pending(self):
        workflow = apply_hard_pod_workflow_overlay(
            {
                'primary_action': {
                    'action_code': 'OA-0009',
                    'execution_label': 'Collect Payment',
                },
            },
            {
                'hard_pod_pending': True,
                'pod_pending': True,
                'log_evidence': {'pod_uploaded': True},
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
                    'applicable': True,
                    'actionable': True,
                    'execute_action_code': 'OA-0008',
                },
            },
        )
        self.assertEqual(workflow['primary_action']['capture_mode'], 'hard_copy_confirmation')
        self.assertNotEqual(workflow['primary_action']['action_code'], 'OA-0009')
