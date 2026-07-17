"""Tests for Job Detail CTA reconciliation."""
from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from mobile_api.job_detail.services.job_detail_navigation_reconciler import (
    _apply_pod_sticky_cta_labels,
    _timeline_row,
    _timeline_through_unloading_completed,
    finalize_job_detail_workflow_cta,
    reconcile_job_detail_cta,
)


class JobDetailNavigationReconcilerTests(SimpleTestCase):
    def test_not_started_promotes_first_pending_start_job_not_pod(self):
        preview = [
            {
                'action_code': 'OA-0001',
                'action_label': 'Start Job',
                'sequence_number': 1,
                'timeline_state': 'pending',
                'is_performed': False,
            },
            {
                'action_code': 'OA-0009',
                'action_label': 'POD',
                'sequence_number': 9,
                'timeline_state': 'pending',
                'is_performed': False,
            },
        ]
        workflow, hint = reconcile_job_detail_cta(
            {'primary_action': {}, 'allowed_actions': []},
            {
                'action': 'refresh_job_detail',
                'screen': 'job_detail',
                'reason': 'Pull to refresh for latest status.',
            },
            timeline={'timeline_preview': preview},
            pod_cod={'pod_pending': True, 'pod_compliant': False},
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'OA-0001')
        self.assertEqual(hint['action_code'], 'OA-0001')
        self.assertNotEqual(hint.get('action'), 'go_to_pod_capture')

    def test_premature_pod_hint_promotes_delivery_arrival_after_departure(self):
        """COD + missing shipment doc must not hide Delivery Arrival CTA."""
        preview = [
            _timeline_row(seq=1, code='OA-0001', label='Start Job', performed=True),
            _timeline_row(seq=2, code='OA-0002', label='Pickup Arrival', performed=True),
            _timeline_row(seq=3, code='OA-0003', label='Start Loading', performed=True),
            _timeline_row(seq=4, code='OA-0004', label='Loading Completed', performed=True),
            _timeline_row(seq=5, code='OA-0005', label='Departure', performed=True),
            _timeline_row(seq=6, code='OA-0006', label='Delivery Arrival', performed=False),
            _timeline_row(seq=9, code='OA-0009', label='POD', performed=False),
        ]
        workflow, hint = reconcile_job_detail_cta(
            {'primary_action': {}, 'allowed_actions': []},
            {
                'action': 'go_to_pod_capture',
                'screen': 'pod_capture',
                'action_code': 'OA-0009',
                'reason': 'Upload proof of delivery.',
            },
            timeline={'timeline_preview': preview},
            pod_cod={
                'pod_pending': True,
                'pod_compliant': False,
                'shipment_document_message': 'Shipment Document missing.',
            },
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'OA-0006')
        self.assertEqual(hint['action_code'], 'OA-0006')
        self.assertNotEqual(hint.get('action'), 'go_to_pod_capture')

    def test_promotes_pending_pod_timeline_row_when_hint_is_refresh(self):
        workflow, hint = reconcile_job_detail_cta(
            {
                'primary_action': {},
                'allowed_actions': [],
            },
            {
                'action': 'refresh_job_detail',
                'screen': 'job_detail',
                'reason': 'Pull to refresh for latest status.',
            },
            timeline={'timeline_preview': _timeline_through_unloading_completed()},
            pod_cod={'pod_pending': True, 'pod_compliant': False},
        )
        self.assertEqual(workflow['primary_action']['action'], 'go_to_pod_capture')
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['action_code'], 'OA-0009')
        self.assertTrue(hint.get('show_pod_capture_button'))
        self.assertIn('primary_button', hint['capture_ui'])

    def test_promotes_label_only_pod_timeline_row_without_navigation(self):
        """Timeline pending rows use action_label — must still surface POD CTA."""
        workflow, hint = reconcile_job_detail_cta(
            {'primary_action': {}, 'allowed_actions': []},
            {
                'action': 'refresh_job_detail',
                'screen': 'job_detail',
                'reason': 'Pull to refresh for latest status.',
            },
            timeline={'timeline_preview': _timeline_through_unloading_completed()},
            pod_cod={'pod_pending': True, 'pod_compliant': False},
        )
        self.assertEqual(workflow['primary_action']['action'], 'go_to_pod_capture')
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['action_code'], 'OA-0009')
        self.assertTrue(hint.get('show_pod_capture_button'))
        self.assertIn('primary_button', hint['capture_ui'])

    def test_overrides_go_to_evidence_capture_when_timeline_pod_pending(self):
        workflow, hint = reconcile_job_detail_cta(
            {'primary_action': {}, 'allowed_actions': []},
            {
                'action': 'go_to_evidence_capture',
                'screen': 'evidence_capture',
                'action_code': 'OA-0009',
                'reason': 'Capture photos, signature, and a short delivery video.',
            },
            timeline={'timeline_preview': _timeline_through_unloading_completed()},
            pod_cod={'pod_pending': True, 'pod_compliant': False},
        )
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertTrue(hint.get('ready_for_pod'))
        self.assertTrue(hint.get('needs_pod_capture'))
        self.assertIn('primary_button', hint['capture_ui'])

    def test_keeps_start_job_hint_when_job_not_started(self):
        preview = [
            {
                'action_code': 'OA-0001',
                'action_label': 'Start Job',
                'sequence_number': 1,
                'timeline_state': 'pending',
                'is_performed': False,
            },
            {
                'action_code': 'OA-0009',
                'action_label': 'POD',
                'sequence_number': 9,
                'timeline_state': 'pending',
                'is_performed': False,
            },
        ]
        workflow, hint = reconcile_job_detail_cta(
            {'primary_action': {}, 'allowed_actions': []},
            {
                'action': 'go_to_evidence_capture',
                'screen': 'evidence_capture',
                'action_code': 'OA-0001',
                'reason': 'Start this job.',
            },
            timeline={'timeline_preview': preview},
            pod_cod={'pod_pending': True, 'pod_compliant': False},
        )
        self.assertEqual(hint['action_code'], 'OA-0001')
        self.assertNotEqual(hint.get('action'), 'go_to_pod_capture')

    def test_does_not_downgrade_go_to_pod_capture_when_end_job_in_allowed(self):
        workflow = {
            'primary_action': {'action_code': 'OA-0009', 'action_label': 'POD'},
            'allowed_actions': [
                {'action_code': 'OA-0009', 'action_label': 'POD'},
                {
                    'action_code': 'OA-0010',
                    'execution_label': 'End Job',
                    'execution_requirements': {'direct_execute': True},
                },
            ],
        }
        pod_cod = {'pod_pending': True, 'pod_compliant': False}
        hint_in = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'OA-0009',
            'show_pod_capture_button': True,
            'capture_ui': {
                'primary_button': {
                    'label': 'Next',
                    'execute_action_code': 'OA-0009',
                },
            },
        }
        from mobile_api.utils.next_action_hint_builder import (
            align_next_action_hint_with_workflow,
        )

        hint = align_next_action_hint_with_workflow(hint_in, workflow, pod_cod)
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['action_code'], 'OA-0009')
        self.assertTrue(hint.get('show_pod_capture_button'))

    def test_promotes_job_close_when_pod_compliant(self):
        close_row = {
            'action_code': 'OA-0010',
            'action_label': 'End Job',
            'action': 'go_to_evidence_capture',
            'screen': 'evidence_capture',
            'ui_mode': 'job_close',
            'timeline_state': 'pending',
            'is_performed': False,
        }
        workflow, hint = reconcile_job_detail_cta(
            {'primary_action': {}},
            {'action': 'refresh_job_detail', 'screen': 'job_detail'},
            timeline={'timeline_preview': [close_row]},
            pod_cod={'pod_pending': False, 'pod_compliant': True},
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'OA-0010')
        self.assertTrue(hint.get('show_close_job_button'))

    def test_promotes_collect_payment_when_pod_compliant_cod(self):
        preview = [
            _timeline_row(seq=9, code='OA-0009', label='POD', performed=True),
            _timeline_row(
                seq=10,
                code='OA-0010',
                label='Payment Collection',
                performed=False,
                execution_requirements={'auto_treasury_post': True},
            ),
            _timeline_row(seq=11, code='OA-0011', label='End Job', performed=False),
        ]
        shipment = SimpleNamespace(order_type='COD', pk='sh-1')
        workflow, hint = reconcile_job_detail_cta(
            {'primary_action': {'action': 'go_to_pod_capture', 'action_code': 'OA-0009'}},
            {'action': 'refresh_job_detail', 'screen': 'job_detail'},
            timeline={'timeline_preview': preview},
            pod_cod={
                'pod_pending': False,
                'pod_compliant': True,
                'hard_pod_pending': False,
                'cod_collected': False,
            },
            shipment=shipment,
        )
        self.assertEqual(workflow['primary_action']['action'], 'go_to_payment_collection')
        self.assertEqual(workflow['primary_action']['action_code'], 'OA-0010')
        self.assertEqual(hint['action'], 'go_to_payment_collection')

    def test_promotes_end_job_when_payment_collection_already_performed(self):
        """Stale Collect Payment CTA must yield to End Job after payment is green."""
        preview = [
            _timeline_row(seq=9, code='OA-0009', label='POD', performed=True),
            _timeline_row(
                seq=10,
                code='OA-0010',
                label='Payment Collection',
                performed=True,
                execution_requirements={'auto_treasury_post': True},
            ),
            _timeline_row(seq=11, code='OA-0011', label='End Job', performed=False),
        ]
        shipment = SimpleNamespace(order_type='COD', pk='sh-1')
        workflow, hint = reconcile_job_detail_cta(
            {
                'primary_action': {
                    'action': 'go_to_payment_collection',
                    'action_code': 'OA-0010',
                    'screen': 'collect_payment',
                },
            },
            {
                'action': 'go_to_payment_collection',
                'screen': 'collect_payment',
                'action_code': 'OA-0010',
            },
            timeline={'timeline_preview': preview},
            pod_cod={
                'pod_pending': False,
                'pod_compliant': True,
                'hard_pod_pending': False,
                'cod_collected': True,
                'cod_pending': False,
            },
            shipment=shipment,
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'OA-0011')
        self.assertEqual(workflow['primary_action']['action_label'], 'End Job')
        self.assertNotEqual(hint.get('action'), 'go_to_payment_collection')
        self.assertEqual(hint.get('action_code'), 'OA-0011')

    def test_promotes_end_job_when_payment_green_even_if_cod_flag_lags(self):
        """Timeline Payment Collection performed wins over stale payment CTA."""
        preview = [
            _timeline_row(seq=9, code='OA-0009', label='POD', performed=True),
            _timeline_row(
                seq=10,
                code='OA-0010',
                label='Payment Collection',
                performed=True,
                execution_requirements={'auto_treasury_post': True},
            ),
            _timeline_row(seq=11, code='OA-0011', label='End Job', performed=False),
        ]
        workflow, hint = reconcile_job_detail_cta(
            {
                'primary_action': {
                    'action': 'go_to_payment_collection',
                    'action_code': 'OA-0010',
                },
            },
            {
                'action': 'go_to_payment_collection',
                'action_code': 'OA-0010',
            },
            timeline={'timeline_preview': preview},
            pod_cod={
                'pod_pending': False,
                'pod_compliant': True,
                'cod_collected': False,
                'cod_pending': True,
            },
            shipment=SimpleNamespace(order_type='COD', pk='sh-1'),
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'OA-0011')
        self.assertNotEqual(hint.get('action'), 'go_to_payment_collection')

    def test_finalize_promotes_end_job_over_stale_payment_hint(self):
        preview = [
            _timeline_row(seq=9, code='OA-0009', label='POD', performed=True),
            _timeline_row(
                seq=10,
                code='OA-0010',
                label='Payment Collection',
                performed=True,
                execution_requirements={'auto_treasury_post': True},
            ),
            _timeline_row(seq=11, code='OA-0011', label='End Job', performed=False),
        ]
        workflow = {
            'primary_action': {
                'action': 'go_to_payment_collection',
                'action_code': 'OA-0010',
                'screen': 'collect_payment',
            },
            'next_action': {'action_code': 'OA-0010'},
            'allowed_actions': [],
        }
        hint = {
            'action': 'go_to_payment_collection',
            'screen': 'collect_payment',
            'action_code': 'OA-0010',
            'screen_title': 'Collect Payment',
        }
        workflow, hint = finalize_job_detail_workflow_cta(
            workflow,
            hint,
            timeline={'timeline_preview': preview},
            pod_cod={
                'pod_pending': False,
                'pod_compliant': True,
                'cod_collected': True,
                'cod_pending': False,
            },
            shipment=SimpleNamespace(order_type='COD', pk='sh-1'),
        )
        self.assertEqual(workflow['primary_action']['action_code'], 'OA-0011')
        self.assertNotEqual(hint.get('action'), 'go_to_payment_collection')

    def test_finalize_promotes_delivery_arrival_sticky_button_after_departure(self):
        """Regression: delivery arrival pending must expose Next on primary_action + hint."""
        preview = [
            _timeline_row(seq=1, code='OA-0001', label='Start Job', performed=True),
            _timeline_row(seq=5, code='OA-0005', label='Departure', performed=True),
            _timeline_row(seq=6, code='OA-0006', label='Delivery Arrival', performed=False),
            _timeline_row(seq=9, code='OA-0009', label='POD', performed=False),
        ]
        workflow = {
            'primary_action': {},
            'next_action': {},
            'allowed_actions': [],
            'reconciliation': {'authoritative_status': 'In Transit'},
        }
        hint = {
            'action': 'refresh_job_detail',
            'screen': 'job_detail',
            'reason': 'Complete proof of delivery before collecting payment.',
        }
        workflow, hint = finalize_job_detail_workflow_cta(
            workflow,
            hint,
            timeline={'timeline_preview': preview},
            pod_cod={'pod_pending': True, 'pod_compliant': False},
            shipment=None,
        )
        primary = workflow['primary_action']
        self.assertEqual(primary['action_code'], 'OA-0006')
        self.assertEqual(primary['action'], 'go_to_evidence_capture')
        self.assertEqual(primary.get('button_label'), 'Delivery Arrival')
        self.assertIn('capture_ui', primary)
        self.assertEqual(workflow['next_action']['action_code'], 'OA-0006')
        self.assertEqual(workflow['next_action']['action'], 'go_to_evidence_capture')
        self.assertEqual(workflow['next_action']['button_label'], 'Delivery Arrival')
        self.assertEqual(workflow['current_stage'], 'In Transit')
        self.assertEqual(len(workflow['allowed_actions']), 1)
        self.assertEqual(hint.get('button_label'), 'Delivery Arrival')

    def test_sticky_button_uses_action_label_not_evidence_next(self):
        row = {
            'action': 'go_to_evidence_capture',
            'action_code': 'OA-0007',
            'action_label': 'Start Unloading',
            'capture_ui': {
                'primary_button': {'label': 'Next', 'action': 'submit_evidence'},
            },
        }
        labeled = _apply_pod_sticky_cta_labels(row)
        self.assertEqual(labeled['button_label'], 'Start Unloading')
        self.assertEqual(
            labeled['capture_ui']['primary_button']['label'],
            'Next',
        )

    def test_finalize_repairs_stale_evidence_primary_when_hint_is_pod(self):
        """Regression: hint correct but primary_action still evidence_capture."""
        hint = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'OA-0009',
            'show_pod_capture_button': True,
            'capture_ui': {
                'primary_button': {
                    'label': 'Next',
                    'action': 'submit_digital_evidence',
                    'execute_action_code': 'OA-0009',
                },
            },
        }
        workflow = {
            'primary_action': {
                'action_code': 'OA-0009',
                'action': 'go_to_evidence_capture',
                'screen': 'evidence_capture',
                'requires_evidence_capture': True,
            },
            'next_action': {
                'action_code': 'OA-0009',
                'action': 'go_to_evidence_capture',
            },
            'allowed_actions': [],
            'workflow_metadata': {'allowed_action_count': 0},
        }
        timeline = {'timeline_preview': _timeline_through_unloading_completed()}
        pod_cod = {'pod_pending': True, 'pod_compliant': False}

        workflow, hint = finalize_job_detail_workflow_cta(
            workflow,
            hint,
            timeline=timeline,
            pod_cod=pod_cod,
        )

        primary = workflow['primary_action']
        self.assertEqual(primary['action'], 'go_to_pod_capture')
        self.assertEqual(primary['screen'], 'pod_capture')
        self.assertTrue(primary.get('show_pod_capture_button'))
        self.assertNotIn('requires_evidence_capture', primary)
        self.assertEqual(workflow['allowed_actions'][0]['action_code'], 'OA-0009')
        self.assertEqual(workflow['workflow_metadata']['allowed_action_count'], 1)
        self.assertTrue(hint.get('show_pod_capture_button'))
        self.assertEqual(primary.get('button_label'), 'POD')

    def test_finalize_sets_operational_stage_pod_while_upload_pending(self):
        hint = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'OA-0009',
            'show_pod_capture_button': True,
            'capture_ui': {
                'primary_button': {
                    'label': 'Next',
                    'execute_action_code': 'OA-0009',
                },
            },
        }
        workflow = {
            'current_stage': 'Delivery',
            'primary_action': {
                'action_code': 'OA-0009',
                'action': 'go_to_evidence_capture',
                'movement_status_impact': 'In Progress',
            },
            'allowed_actions': [],
            'workflow_metadata': {
                'operational_stage': 'Delivery',
                'execution_sub_stage': 'delivery',
            },
        }
        workflow, hint = finalize_job_detail_workflow_cta(
            workflow,
            hint,
            timeline={'timeline_preview': _timeline_through_unloading_completed()},
            pod_cod={'pod_pending': True, 'pod_compliant': False},
        )
        self.assertEqual(workflow['current_stage'], 'Delivered')
        self.assertEqual(workflow['workflow_metadata']['operational_stage'], 'Delivered')
        self.assertEqual(workflow['workflow_metadata']['execution_sub_stage'], 'pod')
        self.assertEqual(workflow['primary_action']['execution_label'], 'POD')
        self.assertNotIn('movement_status_impact', workflow['primary_action'])
        self.assertEqual(hint['button_label'], 'POD')

    def test_finalize_coerces_hard_copy_primary_to_digital_before_upload_log(self):
        hint = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'OA-0008',
            'capture_mode': 'hard_copy_confirmation',
            'active_step': 'hard_copy_confirmation',
            'confirmation_ui': {'ui_mode': 'hard_pod_collection_confirmation'},
            'show_pod_capture_button': True,
        }
        workflow = {
            'primary_action': dict(hint),
            'next_action': dict(hint),
            'allowed_actions': [dict(hint)],
        }
        pod_cod = {
            'pod_pending': True,
            'hard_pod_pending': True,
            'log_evidence': {'pod_uploaded': False},
            'hard_copy_confirmation': {
                'required': True,
                'applicable': True,
                'pending': True,
            },
        }
        workflow, hint = finalize_job_detail_workflow_cta(
            workflow,
            hint,
            timeline={'timeline_preview': _timeline_through_unloading_completed()},
            pod_cod=pod_cod,
        )
        primary = workflow['primary_action']
        self.assertEqual(primary['capture_mode'], 'digital_evidence')
        self.assertEqual(primary['active_step'], 'digital_evidence')
        self.assertNotIn('confirmation_ui', primary)
        self.assertEqual(hint['capture_mode'], 'digital_evidence')

    def test_finalize_keeps_unloading_completed_cta_not_hard_pod(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        hint = {
            'action': 'go_to_evidence_capture',
            'screen': 'evidence_capture',
            'action_code': 'OA-UC',
        }
        workflow = {
            'primary_action': {
                'action_code': 'OA-UC',
                'action_name': 'Unloading Completed',
                'action': 'go_to_evidence_capture',
                'screen': 'evidence_capture',
            },
            'next_action': dict(hint),
            'allowed_actions': [],
        }
        shipment = SimpleNamespace(shipment_status='At Delivery')
        with patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_done',
            return_value=True,
        ), patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_delivery_arrival_done',
            return_value=True,
        ), patch(
            'iroad_tenants.operation_runtime.shipment_execution_stage.shipment_unloading_completed_done',
            return_value=False,
        ):
            workflow, hint = finalize_job_detail_workflow_cta(
                workflow,
                hint,
                timeline={'timeline_preview': []},
                pod_cod={'pod_pending': True, 'hard_pod_pending': True},
                shipment=shipment,
            )
        self.assertEqual(hint['action'], 'go_to_evidence_capture')
        self.assertNotEqual(
            workflow['primary_action'].get('capture_mode'),
            'hard_copy_confirmation',
        )

    def test_finalize_skips_pod_cta_before_unloading_completed(self):
        """NOT_STARTED / pre-unloading jobs must not get Delivered badge or POD CTA."""
        hint = {'action': 'refresh_job_detail', 'screen': 'job_detail'}
        workflow = {
            'current_stage': 'NOT_STARTED',
            'primary_action': {'action_code': 'OA-0001', 'action_label': 'Start Job'},
            'allowed_actions': [],
        }
        timeline = {
            'timeline_preview': [
                {
                    'action_code': 'OA-0001',
                    'action_label': 'Start Job',
                    'sequence_number': 1,
                    'timeline_state': 'pending',
                    'is_performed': False,
                },
                {
                    'action_code': 'OA-0009',
                    'action_label': 'POD',
                    'sequence_number': 9,
                    'timeline_state': 'pending',
                    'is_performed': False,
                },
            ],
        }

        workflow, hint = finalize_job_detail_workflow_cta(
            workflow,
            hint,
            timeline=timeline,
            pod_cod={'pod_pending': True, 'pod_compliant': False},
            shipment=None,
        )

        self.assertEqual(workflow['current_stage'], 'NOT_STARTED')
        self.assertNotEqual(str(hint.get('action') or ''), 'go_to_pod_capture')
