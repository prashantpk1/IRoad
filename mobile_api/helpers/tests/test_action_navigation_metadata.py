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
            {'action_code': 'OA-0009', 'timeline_state': 'pending'},
            None,
            shipment=shipment,
            tenant_schema='tenant_a',
        )
        self.assertEqual(event['action'], 'go_to_payment_collection')
        self.assertEqual(event['screen'], 'collect_payment')

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

    def test_sync_workflow_primary_from_job_close_hint(self):
        workflow = {
            'primary_action': {
                'action_code': 'OA-0010',
                'action_name': 'Job Closed',
            },
            'next_action': {'action_code': 'OA-0010'},
        }
        hint = {
            'action': 'execute_action',
            'screen': 'job_detail',
            'ui_mode': 'job_close',
            'action_code': 'OA-0010',
            'direct_execute': True,
            'show_close_job_button': True,
        }
        from mobile_api.helpers.action_navigation_metadata import (
            sync_workflow_primary_from_job_close_hint,
        )

        out = sync_workflow_primary_from_job_close_hint(workflow, hint)
        self.assertEqual(out['primary_action']['action'], 'execute_action')
        self.assertEqual(out['primary_action']['screen'], 'job_detail')
        self.assertTrue(out['primary_action']['direct_execute'])
        self.assertEqual(out['primary_action']['ui_mode'], 'job_close')

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
