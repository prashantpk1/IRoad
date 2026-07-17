"""Hard POD navigation metadata tests."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from mobile_api.helpers.action_navigation_metadata import (
    apply_hard_copy_navigation_to_action_row,
    enrich_timeline_event_navigation,
)
from tenant_workspace.models import TenantShipment


class ActionNavigationMetadataTests(TestCase):
    @patch(
        'mobile_api.helpers.action_navigation_metadata.build_hard_copy_confirmation_block',
        return_value={
            'required': True,
            'pending': True,
            'actionable': True,
            'action_code': 'A7H',
            'pages': [{'label': 'Page 1', 'page_id': '1'}],
            'submit_endpoint': '/api/v1/mobile/driver/hard-pod/submit/',
            'execute_action_code': 'A7H',
        },
    )
    def test_timeline_pending_hard_pod_includes_checklist_screen(self, _mock_block):
        action = SimpleNamespace(
            action_code='A7H',
            hard_copy_collection=True,
            english_label='Hard POD Collection',
        )
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=2,
        )
        event = enrich_timeline_event_navigation(
            {'action_code': 'A7H', 'event_type': 'hard_pod', 'timeline_state': 'pending'},
            action,
            shipment=shipment,
            tenant_schema='tenant_a',
            log_evidence={'pod_uploaded': True},
        )
        self.assertEqual(event['screen'], 'pod_capture')
        self.assertEqual(event['action'], 'go_to_pod_capture')
        self.assertEqual(event['capture_mode'], 'hard_copy_confirmation')
        self.assertTrue(event['hard_copy_confirmation']['required'])
        self.assertEqual(len(event['hard_copy_confirmation']['pages']), 1)

    @patch(
        'mobile_api.helpers.action_navigation_metadata.build_hard_copy_confirmation_block',
        return_value={
            'required': True,
            'pending': True,
            'actionable': True,
            'action_code': 'A7H',
            'pages': [],
            'submit_endpoint': '/api/v1/mobile/driver/hard-pod/submit/',
            'execute_action_code': 'A7H',
        },
    )
    def test_allowed_action_row_clears_photo_gps_flags(self, _mock_block):
        action = SimpleNamespace(action_code='A7H', hard_copy_collection=True)
        row = apply_hard_copy_navigation_to_action_row(
            {
                'action_code': 'A7H',
                'requires_gps': True,
                'requires_photo': True,
                'execution_requirements': {'gps': True, 'photo': True},
            },
            action,
            shipment=SimpleNamespace(pk=uuid.uuid4(), pod_type=TenantShipment.PodType.HARD),
            tenant_schema='tenant_a',
            log_evidence={'pod_uploaded': True},
        )
        self.assertFalse(row['requires_gps'])
        self.assertFalse(row['requires_photo'])
        self.assertTrue(row['execution_requirements']['custody_submission_required'])

    @patch(
        'mobile_api.helpers.action_navigation_metadata.build_cod_payment_display',
        return_value={'amount_due': '100.00', 'currency_code': 'SAR'},
    )
    @patch(
        'mobile_api.helpers.action_navigation_metadata.pod_cod_policy.derive_pod_cod_flags',
        return_value={
            'pod_pending': False,
            'hard_pod_pending': False,
            'cod_pending': True,
        },
    )
    def test_collect_payment_timeline_routes_to_payment_screen(self, _flags, _payment):
        action = SimpleNamespace(
            action_code='OA-0009',
            auto_treasury_post=True,
            english_label='Collect Payment',
        )
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            order_type='COD',
        )
        event = enrich_timeline_event_navigation(
            {'action_code': 'OA-0009', 'timeline_state': 'pending'},
            action,
            shipment=shipment,
            tenant_schema='tenant_a',
        )
        self.assertEqual(event['screen'], 'collect_payment')
        self.assertEqual(event['action'], 'go_to_payment_collection')
        self.assertEqual(event['amount_due'], '100.00')
        self.assertEqual(
            event['payment_collect_endpoint'],
            '/api/v1/mobile/driver/payments/collect/',
        )

    def test_collect_payment_row_code_only_still_routes_to_payment_screen(self):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.DIGITAL,
            order_type='COD',
        )
        event = enrich_timeline_event_navigation(
            {
                'action_code': 'OA-0009',
                'timeline_state': 'pending',
                'execution_requirements': {'auto_treasury_post': True},
            },
            None,
            shipment=shipment,
            tenant_schema='tenant_a',
        )
        self.assertEqual(event['action'], 'go_to_payment_collection')
        self.assertEqual(event['screen'], 'collect_payment')

    def test_payment_collection_label_routes_to_payment_not_evidence(self):
        """Dynamic OA label 'Payment Collection' must not open evidence execute."""
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.DIGITAL,
            order_type='COD',
        )
        event = enrich_timeline_event_navigation(
            {
                'action_code': 'OA-0010',
                'action_label': 'Payment Collection',
                'english_label': 'Payment Collection',
                'timeline_state': 'pending',
                'action': 'go_to_evidence_capture',
                'screen': 'evidence_capture',
                'requires_evidence_capture': True,
            },
            None,
            shipment=shipment,
            tenant_schema='tenant_a',
        )
        self.assertEqual(event['action'], 'go_to_payment_collection')
        self.assertEqual(event['screen'], 'collect_payment')
        self.assertFalse(event.get('requires_evidence_capture'))
        self.assertNotIn('capture_ui', event)
        self.assertEqual(
            event['payment_collect_endpoint'],
            '/api/v1/mobile/driver/payments/collect/',
        )

    def test_sync_workflow_primary_from_payment_hint(self):
        workflow = {
            'primary_action': {
                'action_code': 'OA-0009',
                'action_name': 'Collect Payment',
            },
            'next_action': {'action_code': 'OA-0009'},
        }
        hint = {
            'action': 'go_to_payment_collection',
            'screen': 'collect_payment',
            'payment_collect_endpoint': '/api/v1/mobile/driver/payments/collect/',
            'amount_due': '100.00',
        }
        from mobile_api.helpers.action_navigation_metadata import (
            sync_workflow_primary_from_payment_hint,
        )

        out = sync_workflow_primary_from_payment_hint(workflow, hint)
        self.assertEqual(out['primary_action']['action'], 'go_to_payment_collection')
        self.assertEqual(out['primary_action']['screen'], 'collect_payment')
        self.assertEqual(out['primary_action']['amount_due'], '100.00')

    def test_sync_workflow_primary_from_payment_hint_seeds_when_primary_stale_pod(self):
        workflow = {
            'primary_action': {
                'action_code': 'OA-0009',
                'action': 'go_to_pod_capture',
                'action_name': 'POD',
            },
            'next_action': {},
        }
        hint = {
            'action': 'go_to_payment_collection',
            'screen': 'collect_payment',
            'action_code': 'OA-0010',
            'screen_title': 'Collect Payment',
            'payment_collect_endpoint': '/api/v1/mobile/driver/payments/collect/',
        }
        from mobile_api.helpers.action_navigation_metadata import (
            sync_workflow_primary_from_payment_hint,
        )

        out = sync_workflow_primary_from_payment_hint(workflow, hint)
        self.assertEqual(out['primary_action']['action'], 'go_to_payment_collection')
        self.assertEqual(out['primary_action']['action_code'], 'OA-0010')
        self.assertEqual(out['primary_action']['action_label'], 'Collect Payment')

    def test_movement_workflow_row_routes_to_evidence_capture(self):
        from mobile_api.helpers.action_navigation_metadata import enrich_workflow_pod_navigation

        workflow = enrich_workflow_pod_navigation(
            {
                'allowed_actions': [
                    {
                        'action_code': 'EM1',
                        'action_name': 'Start Empty Move',
                        'execution_requirements': {'direct_execute': True},
                    },
                ],
                'primary_action': {
                    'action_code': 'EM1',
                    'action_name': 'Start Empty Move',
                },
            },
            shipment=None,
        )
        row = workflow['primary_action']
        self.assertEqual(row['action'], 'go_to_evidence_capture')
        self.assertEqual(row['screen'], 'evidence_capture')
        self.assertTrue(row['requires_evidence_capture'])
        media_types = [s['media_type'] for s in row['capture_ui']['sections']]
        self.assertEqual(media_types[:2], ['photo', 'video'])

    def test_sync_workflow_primary_from_job_close_hint(self):
        workflow = {
            'primary_action': {
                'action_code': 'OA-0010',
                'action_name': 'Job Closed',
            },
            'next_action': {'action_code': 'OA-0010'},
        }
        hint = {
            'action': 'go_to_evidence_capture',
            'screen': 'evidence_capture',
            'ui_mode': 'job_close',
            'action_code': 'OA-0010',
            'direct_execute': False,
            'requires_evidence_capture': True,
            'show_close_job_button': True,
        }
        from mobile_api.helpers.action_navigation_metadata import (
            sync_workflow_primary_from_job_close_hint,
        )

        out = sync_workflow_primary_from_job_close_hint(workflow, hint)
        self.assertEqual(out['primary_action']['action'], 'go_to_evidence_capture')
        self.assertEqual(out['primary_action']['screen'], 'evidence_capture')
        self.assertFalse(out['primary_action']['direct_execute'])
        self.assertEqual(out['primary_action']['ui_mode'], 'job_close')

    def test_sync_workflow_primary_from_pod_capture_hint(self):
        workflow = {
            'primary_action': {},
            'next_action': {},
            'allowed_actions': [],
        }
        hint = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'OA-0008',
            'capture_mode': 'digital_evidence',
            'ui_mode': 'digital_evidence',
            'screen_title': 'Capturing Action Evidences',
            'pod_capture_steps': [{'step': 'digital_evidence'}],
            'capture_ui': {
                'primary_button': {
                    'label': 'Next',
                    'action': 'submit_digital_evidence',
                    'execute_action_code': 'OA-0008',
                },
            },
        }
        from mobile_api.helpers.action_navigation_metadata import (
            sync_workflow_primary_from_next_hint,
        )

        out = sync_workflow_primary_from_next_hint(workflow, hint)
        self.assertEqual(out['primary_action']['action'], 'go_to_pod_capture')
        self.assertEqual(out['primary_action']['screen'], 'pod_capture')
        self.assertEqual(out['primary_action']['action_code'], 'OA-0008')
        self.assertIn('primary_button', out['primary_action']['capture_ui'])

    def test_sync_workflow_primary_from_pod_capture_overrides_stale_primary(self):
        workflow = {
            'primary_action': {
                'action_code': 'OA-0007',
                'english_label': 'Start Unloading',
                'action': 'go_to_evidence_capture',
            },
            'next_action': {'action_code': 'OA-0007'},
        }
        hint = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'OA-0009',
            'capture_mode': 'digital_evidence',
        }
        from mobile_api.helpers.action_navigation_metadata import (
            sync_workflow_primary_from_next_hint,
        )

        out = sync_workflow_primary_from_next_hint(workflow, hint)
        self.assertEqual(out['primary_action']['action'], 'go_to_pod_capture')
        self.assertEqual(out['primary_action']['action_code'], 'OA-0009')
        self.assertEqual(out['primary_action']['english_label'], 'Start Unloading')

    def test_enrich_preserves_pod_capture_primary_after_hint_sync(self):
        """Regression: enrich must not downgrade synced POD CTA to evidence capture."""
        hint = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'OA-0009',
            'capture_mode': 'digital_evidence',
            'ui_mode': 'digital_evidence',
            'screen_title': 'Capturing Action Evidences',
            'pod_capture_steps': ['digital_evidence'],
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
            'next_action': {'action_code': 'OA-0009'},
            'allowed_actions': [],
        }
        from mobile_api.helpers.action_navigation_metadata import (
            enrich_workflow_pod_navigation,
            sync_workflow_primary_from_next_hint,
        )

        workflow = sync_workflow_primary_from_next_hint(workflow, hint)
        workflow = enrich_workflow_pod_navigation(workflow, shipment=None)
        primary = workflow['primary_action']
        self.assertEqual(primary['action'], 'go_to_pod_capture')
        self.assertEqual(primary['screen'], 'pod_capture')
        self.assertEqual(primary['action_code'], 'OA-0009')
        self.assertEqual(
            primary['capture_ui']['primary_button']['action'],
            'submit_digital_evidence',
        )
        self.assertNotIn('requires_evidence_capture', primary)

    @patch(
        'mobile_api.helpers.action_navigation_metadata.build_hard_copy_navigation_payload',
        return_value={
            'screen': 'pod_capture',
            'action': 'go_to_pod_capture',
            'capture_mode': 'hard_copy_confirmation',
            'screen_title': 'Hard POD Collection Confirmation',
        },
    )
    @patch(
        'mobile_api.helpers.action_navigation_metadata._hard_copy_applicable',
        return_value=(True, {'pending': True}),
    )
    @patch(
        'mobile_api.helpers.action_navigation_metadata.pod_cod_policy.derive_pod_cod_flags',
        return_value={
            'pod_pending': False,
            'hard_pod_pending': True,
            'cod_pending': True,
        },
    )
    def test_collect_payment_timeline_redirects_when_hard_pod_pending(
        self,
        _flags,
        _applicable,
        _hard_nav,
    ):
        action = SimpleNamespace(
            action_code='OA-0009',
            auto_treasury_post=True,
            english_label='Collect Payment',
        )
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.DIGITAL,
            booking=SimpleNamespace(pod_type=TenantShipment.PodType.HARD),
            order_type='COD',
        )
        event = enrich_timeline_event_navigation(
            {'action_code': 'OA-0009', 'timeline_state': 'pending'},
            action,
            shipment=shipment,
            tenant_schema='tenant_a',
            log_evidence={'pod_uploaded': True},
        )
        self.assertEqual(event['screen'], 'pod_capture')
        self.assertEqual(event['capture_mode'], 'hard_copy_confirmation')
        self.assertEqual(event['redirected_from'], 'collect_payment')
        self.assertEqual(
            event['execution_label'],
            'Hard POD Collection Confirmation',
        )

    def test_performed_action_log_timeline_has_no_forward_navigation(self):
        action = SimpleNamespace(
            action_code='OA-0008',
            auto_pod_post=True,
            hard_copy_collection=True,
            english_label='POD',
        )
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
        )
        event = enrich_timeline_event_navigation(
            {
                'action_code': 'OA-0008',
                'authority': 'action_log',
                'timeline_state': 'performed',
                'is_performed': True,
            },
            action,
            shipment=shipment,
            tenant_schema='tenant_a',
            log_evidence={'pod_uploaded': True, 'hard_pod_log': True},
        )
        self.assertEqual(event['action_code'], 'OA-0008')
        self.assertNotIn('action', event)
        self.assertNotIn('confirmation_ui', event)

    @patch(
        'mobile_api.helpers.action_navigation_metadata._ensure_pod_row_capture_ui',
        side_effect=lambda row, *a, **k: row,
    )
    @patch(
        'mobile_api.helpers.action_navigation_metadata.build_hard_copy_confirmation_block',
        return_value={
            'required': True,
            'pending': True,
            'applicable': True,
            'actionable': False,
            'confirmation_ui': {'ui_mode': 'hard_pod_collection_confirmation'},
            'pages': [{'label': 'IMG-(SH-001-001)'}],
        },
    )
    @patch(
        'mobile_api.helpers.action_navigation_metadata._hard_pod_includes_wizard_hard_copy_step',
        return_value=True,
    )
    @patch(
        'mobile_api.helpers.action_navigation_metadata._digital_pod_complete',
        return_value=False,
    )
    def test_pod_upload_row_opens_digital_without_hard_copy_confirmation_ui(
        self,
        _digital,
        _wizard,
        _block,
        _capture_ui,
    ):
        from mobile_api.helpers.action_navigation_metadata import apply_pod_upload_navigation

        action = SimpleNamespace(
            action_code='OA-0008',
            auto_pod_post=True,
            hard_copy_collection=True,
            english_label='POD',
        )
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
        )
        row = apply_pod_upload_navigation(
            {'action_code': 'OA-0008', 'action_name': 'POD'},
            action,
            shipment=shipment,
            tenant_schema='tenant_a',
            log_evidence={'pod_uploaded': False},
        )
        self.assertEqual(row['active_step'], 'digital_evidence')
        self.assertEqual(row['capture_mode'], 'digital_evidence')
        self.assertNotIn('confirmation_ui', row)
        self.assertTrue(row['includes_hard_copy'])

    def test_finalize_timeline_promotes_label_only_pod_row(self):
        from mobile_api.helpers.action_navigation_metadata import (
            finalize_timeline_preview_navigation,
        )
        from mobile_api.job_detail.services.job_detail_navigation_reconciler import (
            _timeline_through_unloading_completed,
        )

        preview = finalize_timeline_preview_navigation(
            _timeline_through_unloading_completed(),
            shipment=SimpleNamespace(shipment_status='At Delivery'),
            tenant_schema='tenant_a',
            log_evidence={},
        )
        pod_rows = [row for row in preview if str(row.get('action_code') or '') == 'OA-0009']
        self.assertEqual(len(pod_rows), 1)
        row = pod_rows[0]
        self.assertEqual(row['action'], 'go_to_pod_capture')
        self.assertIn('primary_button', row['capture_ui'])

    def test_finalize_timeline_keeps_pod_inert_before_unloading(self):
        from mobile_api.helpers.action_navigation_metadata import (
            finalize_timeline_preview_navigation,
        )

        preview = finalize_timeline_preview_navigation(
            [
                {
                    'action_code': 'OA-0009',
                    'action_label': 'POD',
                    'sequence_number': 9,
                    'timeline_state': 'pending',
                    'is_performed': False,
                },
            ],
            shipment=SimpleNamespace(shipment_status='Created'),
            tenant_schema='tenant_a',
            log_evidence={},
        )
        row = preview[0]
        self.assertNotIn('action', row)
        self.assertNotIn('capture_ui', row)

    def test_pod_hint_does_not_merge_hard_copy_onto_unloading_completed(self):
        from mobile_api.helpers.action_navigation_metadata import (
            sync_workflow_primary_from_pod_capture_hint,
        )

        workflow = {
            'primary_action': {
                'action_code': 'OA-0008',
                'action_name': 'Unloading Completed',
                'action': 'go_to_evidence_capture',
                'screen': 'evidence_capture',
                'requires_evidence_capture': True,
            },
        }
        hint = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'capture_mode': 'hard_copy_confirmation',
            'active_step': 'hard_copy_confirmation',
            'show_pod_capture_button': True,
            'confirmation_ui': {'ui_mode': 'hard_pod_collection_confirmation'},
        }
        out = sync_workflow_primary_from_pod_capture_hint(workflow, hint)
        primary = out['primary_action']
        self.assertEqual(primary['action'], 'go_to_evidence_capture')
        self.assertEqual(primary['action_name'], 'Unloading Completed')
        self.assertNotEqual(primary.get('capture_mode'), 'hard_copy_confirmation')
        self.assertNotIn('confirmation_ui', primary)
