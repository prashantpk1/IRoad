"""Unit tests for next_action_hint builder."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.utils.next_action_hint_builder import (
    align_next_action_hint_with_workflow,
    build_next_action_hint,
)

_JOB_CLOSE_ROW = {
    'action_code': 'OA-0010',
    'english_label': 'Job Closed',
    'execution_requirements': {
        'direct_execute': True,
        'shipment_status_impact': 'Closed',
    },
}
_START_JOB_ROW = {
    'action_code': 'OA-0001',
    'english_label': 'Start Job',
    'execution_requirements': {'direct_execute': True},
}
_UNLOADING_ROW = {
    'action_code': 'OA-0007',
    'english_label': 'Start Unloading',
}
_CONFIRM_LOADED_ROW = {
    'action_code': 'OA-0004',
    'english_label': 'Confirm Loaded',
    'execution_requirements': {'auto_shipment_post': True},
}


class NextActionHintBuilderTests(SimpleTestCase):
    def test_job_close_next_shows_close_job(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [_JOB_CLOSE_ROW],
                'next_action': {'action_code': 'OA-0010'},
                'reconciliation': {'column_status': 'Delivered'},
            },
            pod_cod={'pod_compliant': True, 'pod_pending': False},
            order_type='Credit',
        )
        self.assertEqual(hint['action_code'], 'OA-0010')
        self.assertEqual(hint['action'], 'go_to_evidence_capture')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertFalse(hint.get('direct_execute'))
        self.assertTrue(hint.get('requires_evidence_capture'))

    def test_cod_payment_complete_pod_submitted_shows_close_job_without_workflow_a10(
        self,
    ):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [_JOB_CLOSE_ROW],
                'next_action': {},
                'reconciliation': {'column_status': 'POD Submitted'},
            },
            pod_cod={
                'pod_compliant': True,
                'pod_pending': False,
                'cod_collected': True,
                'cod_pending': False,
                'treasury_pending': False,
                'delivery_blocked': False,
            },
            order_type='COD',
        )
        self.assertEqual(hint['action_code'], 'OA-0010')
        self.assertTrue(hint.get('show_close_job_button'))

    def test_after_collect_payment_execute_hints_job_close(self):
        outbound = MagicMock()
        outbound.shipment_status = 'Delivered'

        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0009',
                        'execution_requirements': {'auto_treasury_post': True},
                    },
                    _JOB_CLOSE_ROW,
                ],
                'next_action': {'action_code': 'OA-0009'},
            },
            pod_cod={
                'pod_compliant': True,
                'pod_pending': False,
                'cod_collected': True,
                'cod_pending': False,
                'treasury_pending': False,
                'delivery_blocked': False,
            },
            action_code='OA-0009',
            order_type='COD',
            shipment=outbound,
        )
        self.assertEqual(hint['action_code'], 'OA-0010')
        self.assertEqual(hint['action'], 'go_to_evidence_capture')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertFalse(hint.get('direct_execute'))
        self.assertTrue(hint.get('requires_evidence_capture'))
        self.assertTrue(hint.get('payment_collected'))

    def test_after_collect_payment_round_trip_shows_end_job_not_return_leg(self):
        booking = MagicMock()
        booking.pk = 'bk-round-1'
        booking.booking_id = booking.pk
        booking.booking_no = 'BK-0043'
        booking.trip_type = 'Round'
        booking.assigned_driver_id = 'drv-1'
        booking.booking_line_backload_driver_id = 'drv-1'
        outbound = MagicMock()
        outbound.pk = 'sh-1'
        outbound.booking_item_type = 'Outbound'
        outbound.shipment_status = 'Delivered'
        outbound.shipment_sequence = 1
        outbound.order_type = 'COD'
        outbound.pod_status = 'Completed'
        outbound.collection_status = 'Collected'
        booking.shipments = MagicMock()
        booking.shipments.all.return_value = [outbound]

        driver = MagicMock()
        driver.pk = 'drv-1'

        with patch(
            'iroad_tenants.operation_runtime.side_effects._mobile_pod_compliance_satisfied',
            return_value=True,
        ):
            hint = build_next_action_hint(
                workflow={
                    'allowed_actions': [
                        {
                            'action_code': 'OA-0009',
                            'execution_requirements': {'auto_treasury_post': True},
                        },
                        _JOB_CLOSE_ROW,
                    ],
                    'next_action': _JOB_CLOSE_ROW,
                },
                pod_cod={
                    'pod_compliant': True,
                    'pod_pending': False,
                    'cod_collected': True,
                    'cod_pending': False,
                    'treasury_pending': False,
                    'delivery_blocked': False,
                },
                action_code='OA-0009',
                order_type='COD',
                booking=booking,
                shipment=outbound,
                driver=driver,
            )
        self.assertNotEqual(hint.get('action'), 'navigate_open_job')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertIn('End Job', str(hint.get('reason') or ''))

    def test_round_trip_outbound_pod_complete_shows_end_job_before_return(self):
        booking = MagicMock()
        booking.pk = 'bk-round-1'
        booking.booking_id = booking.pk
        booking.booking_no = 'BK-0043'
        booking.trip_type = 'Round'
        booking.assigned_driver_id = 'drv-1'
        booking.booking_line_backload_driver_id = 'drv-1'
        outbound = MagicMock()
        outbound.pk = 'sh-1'
        outbound.booking_item_type = 'Outbound'
        outbound.shipment_status = 'Delivered'
        outbound.shipment_sequence = 1
        outbound.order_type = 'COD'
        outbound.pod_status = 'Completed'
        outbound.collection_status = 'Collected'
        booking.shipments = MagicMock()
        booking.shipments.all.return_value = [outbound]

        driver = MagicMock()
        driver.pk = 'drv-1'

        with patch(
            'iroad_tenants.operation_runtime.side_effects._mobile_pod_compliance_satisfied',
            return_value=True,
        ):
            hint = build_next_action_hint(
                workflow={
                    'allowed_actions': [_JOB_CLOSE_ROW],
                    'next_action': _JOB_CLOSE_ROW,
                },
                pod_cod={
                    'pod_compliant': True,
                    'pod_pending': False,
                    'cod_collected': True,
                    'cod_pending': False,
                    'treasury_pending': False,
                    'delivery_blocked': False,
                },
                order_type='COD',
                booking=booking,
                shipment=outbound,
                driver=driver,
            )
        self.assertNotEqual(hint.get('action'), 'navigate_open_job')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertIn('End Job', str(hint.get('reason') or ''))

    def test_round_trip_backload_complete_still_shows_close_job(self):
        booking = MagicMock()
        booking.pk = 'bk-round-2'
        booking.booking_id = booking.pk
        booking.trip_type = 'Round'
        outbound = MagicMock()
        outbound.pk = 'sh-1'
        outbound.booking_item_type = 'Outbound'
        outbound.shipment_status = 'Closed'
        outbound.shipment_sequence = 1
        backload = MagicMock()
        backload.pk = 'sh-2'
        backload.booking_item_type = 'Backload'
        backload.shipment_status = 'Delivered'
        backload.shipment_sequence = 2
        booking.shipments = MagicMock()
        booking.shipments.all.return_value = [outbound, backload]

        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [_JOB_CLOSE_ROW],
                'next_action': _JOB_CLOSE_ROW,
            },
            pod_cod={
                'pod_compliant': True,
                'pod_pending': False,
                'cod_collected': True,
                'cod_pending': False,
                'treasury_pending': False,
                'delivery_blocked': False,
            },
            order_type='COD',
            booking=booking,
            shipment=backload,
        )
        self.assertEqual(hint['action'], 'go_to_evidence_capture')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertFalse(hint.get('direct_execute'))
        self.assertTrue(hint.get('requires_evidence_capture'))

    def test_after_job_close_execute_go_dashboard(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [_JOB_CLOSE_ROW],
                'next_action': {},
            },
            pod_cod={},
            action_code='OA-0010',
            order_type='Credit',
        )
        self.assertTrue(hint['job_closed'])
        self.assertEqual(hint['action'], 'go_to_dashboard')

    def test_after_job_close_round_trip_outbound_hints_open_return_job(self):
        booking = MagicMock()
        booking.pk = 'bk-round-1'
        booking.booking_id = booking.pk
        booking.booking_no = 'BK-0043'
        booking.trip_type = 'Round'
        booking.assigned_driver_id = 'drv-1'
        booking.booking_line_backload_driver_id = 'drv-1'
        booking.shipments = MagicMock()
        outbound = MagicMock()
        outbound.booking_item_type = 'Outbound'
        outbound.shipment_status = 'Closed'
        outbound.shipment_sequence = 1
        booking.shipments.all.return_value = [outbound]

        driver = MagicMock()
        driver.pk = 'drv-1'
        driver.driver_id = 'drv-1'

        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [_JOB_CLOSE_ROW],
                'next_action': {},
            },
            pod_cod={},
            action_code='OA-0010',
            order_type='Credit',
            booking=booking,
            driver=driver,
        )
        self.assertEqual(hint['action'], 'navigate_open_job')
        self.assertEqual(hint['screen'], 'job_detail')
        self.assertFalse(hint['job_closed'])
        self.assertTrue(hint.get('booking_continues'))
        self.assertTrue(hint.get('leg_completed'))
        open_job = hint.get('open_job') or {}
        self.assertEqual(open_job.get('job_type'), 'booking')
        self.assertEqual(open_job.get('job_id'), 'bk-round-1')
        self.assertEqual(open_job.get('booking_item_type'), 'Backload')
        self.assertTrue(open_job.get('backload_bootstrap_pending'))

    def test_start_job_hint_includes_optional_capture_ui(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [_START_JOB_ROW],
                'next_action': {'action_code': 'OA-0001'},
            },
        )
        capture_ui = hint.get('capture_ui') or {}
        photo = next(
            (s for s in capture_ui.get('sections') or [] if s.get('media_type') == 'photo'),
            {},
        )
        self.assertTrue(hint.get('allow_submit_without_media'))
        self.assertFalse(photo.get('required'))
        self.assertEqual(photo.get('min_count'), 0)
        self.assertTrue(capture_ui.get('primary_button', {}).get('allow_empty_media'))

    def test_a7_routes_to_pod_capture(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [{'action_code': 'A7'}],
                'next_action': {'action_code': 'A7'},
            },
            pod_cod={},
            order_type='Credit',
        )
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['capture_mode'], 'digital_evidence')
        self.assertEqual(hint['screen_title'], 'Capturing Action Evidences')
        self.assertEqual(hint['pod_capture_steps'], ['digital_evidence'])

    def test_closed_job_with_no_actions_returns_dashboard(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [],
                'next_action': {},
                'reconciliation': {'column_status': 'Closed'},
            },
            pod_cod={},
            order_type='COD',
        )
        self.assertEqual(hint['action'], 'go_to_dashboard')
        self.assertTrue(hint['job_closed'])

    def test_unloading_before_hard_copy_at_delivery(self):
        shipment = SimpleNamespace(shipment_status='At Delivery')
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0007',
                        'english_label': 'Start Unloading',
                    },
                ],
                'next_action': {'action_code': 'OA-0008'},
            },
            pod_cod={
                'hard_pod_pending': True,
                'pod_pending': False,
                'log_evidence': {'pod_uploaded': True},
                'unloading_pending': True,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
                    'applicable': True,
                    'actionable': True,
                    'execute_action_code': 'OA-0008',
                },
            },
            order_type='COD',
            shipment=shipment,
        )
        self.assertEqual(hint['action_code'], 'OA-0007')
        self.assertEqual(hint['action'], 'go_to_evidence_capture')

    def test_after_pod_routes_to_hard_copy_when_digital_complete(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0008',
                        'execution_requirements': {'hard_copy_collection': True},
                    },
                ],
                'next_action': {'action_code': 'OA-0008'},
            },
            pod_cod={
                'hard_pod_pending': True,
                'pod_pending': False,
                'pod_compliant': False,
                'log_evidence': {'pod_uploaded': True},
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
                    'applicable': True,
                    'actionable': True,
                    'execute_action_code': 'OA-0010',
                },
            },
            action_code='OA-0008',
            order_type='COD',
        )
        self.assertEqual(hint['action_code'], 'OA-0010')
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['capture_mode'], 'hard_copy_confirmation')

    def test_unloading_only_when_hard_copy_complete(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [_UNLOADING_ROW],
                'next_action': {'action_code': 'OA-0007'},
            },
            pod_cod={
                'hard_pod_pending': False,
                'pod_pending': False,
                'pod_compliant': True,
            },
            order_type='COD',
        )
        self.assertEqual(hint['action_code'], 'OA-0007')
        self.assertEqual(hint['action'], 'go_to_evidence_capture')

    def test_hard_pod_pending_after_a9_routes_to_hard_copy_not_ops_wait(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [],
                'next_action': {},
            },
            pod_cod={
                'hard_pod_pending': True,
                'pod_pending': False,
                'pod_compliant': False,
                'log_evidence': {'pod_uploaded': True},
                'delivery_blocked': True,
                'cod_collected': True,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
                    'applicable': True,
                    'actionable': True,
                },
            },
            order_type='COD',
        )
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['capture_mode'], 'hard_copy_confirmation')
        self.assertNotEqual(hint['action'], 'wait_for_ops')

    def test_hard_pod_pending_routes_hard_copy_only_after_digital(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0008',
                        'execution_requirements': {'hard_copy_collection': True},
                    },
                ],
                'next_action': {'action_code': 'OA-0008'},
            },
            pod_cod={
                'hard_pod_pending': True,
                'pod_pending': False,
                'log_evidence': {'pod_uploaded': True},
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
                    'applicable': True,
                    'actionable': True,
                    'execute_action_code': 'OA-0008',
                },
            },
            order_type='COD',
        )
        self.assertEqual(hint['action_code'], 'OA-0008')
        self.assertEqual(hint['screen'], 'pod_capture')
        self.assertEqual(hint['capture_mode'], 'hard_copy_confirmation')
        self.assertFalse(hint['requires_multipart'])

    def test_digital_pod_next_uses_tenant_action_code(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0008',
                        'execution_requirements': {'auto_pod_post': True},
                    },
                ],
                'next_action': {'action_code': 'OA-0008'},
            },
            pod_cod={'pod_pending': True},
            order_type='Credit',
        )
        self.assertEqual(hint['action_code'], 'OA-0008')
        self.assertEqual(hint['capture_mode'], 'digital_evidence')

    def test_hard_pod_pending_without_digital_routes_upload_pod_not_hard_copy(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0008',
                        'execution_requirements': {
                            'auto_pod_post': True,
                            'hard_copy_collection': True,
                        },
                    },
                ],
                'next_action': {'action_code': 'OA-0008'},
            },
            pod_cod={
                'pod_pending': False,
                'hard_pod_pending': True,
                'digital_evidence_complete': False,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
                    'applicable': True,
                    'execute_action_code': 'OA-0008',
                },
            },
            order_type='COD',
        )
        self.assertEqual(hint['capture_mode'], 'digital_evidence')
        self.assertNotEqual(hint.get('capture_mode'), 'hard_copy_confirmation')

    def test_hard_pod_pending_without_digital_second_branch(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0008',
                        'execution_requirements': {
                            'auto_pod_post': True,
                            'hard_copy_collection': True,
                        },
                    },
                ],
                'next_action': {'action_code': 'OA-0008'},
            },
            pod_cod={
                'pod_pending': True,
                'hard_pod_pending': True,
                'pod_type': 'Hard',
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
                    'execute_action_code': 'OA-0008',
                },
            },
            order_type='Credit',
        )
        self.assertEqual(hint['action_code'], 'OA-0008')
        self.assertEqual(hint['capture_mode'], 'digital_evidence')
        self.assertEqual(
            hint['pod_capture_steps'],
            ['digital_evidence', 'hard_copy_confirmation'],
        )
        self.assertTrue(hint.get('hard_pod'))

    def test_cod_collect_payment_uses_tenant_action_code(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0009',
                        'execution_requirements': {'auto_treasury_post': True},
                    },
                ],
                'next_action': {'action_code': 'OA-0009'},
            },
            pod_cod={'cod_pending': True, 'cod_collected': False},
            order_type='COD',
        )
        self.assertEqual(hint['action_code'], 'OA-0009')
        self.assertEqual(hint['screen'], 'collect_payment')
        self.assertEqual(hint['action'], 'go_to_payment_collection')

    def test_oa_0010_close_hint_evidence_capture(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0010',
                        'execution_requirements': {
                            'direct_execute': True,
                            'shipment_status_impact': 'Closed',
                        },
                    },
                ],
                'next_action': {'action_code': 'OA-0010'},
            },
            pod_cod={
                'pod_compliant': True,
                'cod_collected': True,
                'treasury_pending': False,
            },
            order_type='COD',
            shipment=SimpleNamespace(shipment_status='Delivered'),
        )
        self.assertEqual(hint['action_code'], 'OA-0010')
        self.assertEqual(hint['action'], 'go_to_evidence_capture')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertFalse(hint.get('direct_execute'))
        self.assertTrue(hint.get('requires_evidence_capture'))
        self.assertFalse(hint.get('requires_multipart'))

    def test_requires_multipart_false_for_optional_evidence_start_job(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0001',
                        'execution_requirements': {
                            'direct_execute': True,
                            'photo': False,
                            'auto_shipment_post': False,
                        },
                    },
                ],
                'next_action': {'action_code': 'OA-0001'},
            },
        )
        self.assertEqual(hint['action_code'], 'OA-0001')
        self.assertFalse(hint['requires_multipart'])

    def test_requires_multipart_true_for_auto_shipment_and_photos(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0004',
                        'execution_requirements': {
                            'photo': True,
                            'photo_min_count': 2,
                            'auto_shipment_post': True,
                        },
                    },
                ],
                'next_action': {'action_code': 'OA-0004'},
            },
        )
        self.assertEqual(hint['action_code'], 'OA-0004')
        self.assertTrue(hint['requires_multipart'])

    def test_requires_multipart_true_for_confirm_loaded(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [_CONFIRM_LOADED_ROW],
                'next_action': {'action_code': 'OA-0004'},
            },
        )
        self.assertEqual(hint['action_code'], 'OA-0004')
        self.assertTrue(hint['requires_multipart'])

    def test_requires_multipart_true_for_legacy_a4_label(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'CUSTOM-LOAD-01',
                        'english_label': 'Confirm Loaded',
                        'execution_requirements': {'auto_shipment_post': True},
                    },
                ],
                'next_action': {'action_code': 'CUSTOM-LOAD-01'},
            },
        )
        self.assertEqual(hint['action_code'], 'CUSTOM-LOAD-01')
        self.assertTrue(hint['requires_multipart'])

    def test_align_fixes_execute_hint_to_digital_pod_capture(self):
        workflow = {
            'allowed_actions': [
                {
                    'action_code': 'OA-0008',
                    'action': 'go_to_pod_capture',
                    'capture_mode': 'digital_evidence',
                    'active_step': 'digital_evidence',
                    'execution_requirements': {
                        'auto_pod_post': True,
                        'hard_copy_collection': True,
                    },
                    'pod_capture_steps': [
                        'digital_evidence',
                        'hard_copy_confirmation',
                    ],
                    'hard_pod': True,
                },
            ],
            'primary_action': {
                'action_code': 'OA-0008',
                'action': 'go_to_pod_capture',
                'capture_mode': 'digital_evidence',
                'pod_capture_steps': [
                    'digital_evidence',
                    'hard_copy_confirmation',
                ],
                'hard_pod': True,
            },
            'next_action': {'action_code': 'OA-0008'},
        }
        pod_cod = {
            'pod_pending': True,
            'hard_pod_pending': True,
            'hard_copy_confirmation': {'required': True, 'pending': True},
        }
        wrong_hint = {
            'action': 'execute_action',
            'screen': 'job_detail',
            'action_code': 'OA-0008',
            'requires_multipart': True,
        }
        hint = align_next_action_hint_with_workflow(wrong_hint, workflow, pod_cod)
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['capture_mode'], 'digital_evidence')
        self.assertEqual(
            hint['pod_capture_steps'],
            ['digital_evidence', 'hard_copy_confirmation'],
        )
        self.assertTrue(hint.get('hard_pod'))
        self.assertFalse(hint['requires_multipart'])

    def test_align_job_close_when_hard_copy_not_required(self):
        workflow = {
            'primary_action': {
                'action_code': 'OA-0010',
                'execution_label': 'Job Closed',
                'execution_requirements': {'direct_execute': True},
            },
            'allowed_actions': [
                {
                    'action_code': 'OA-0010',
                    'execution_label': 'Job Closed',
                    'execution_requirements': {'direct_execute': True},
                },
            ],
        }
        pod_cod = {
            'pod_pending': False,
            'hard_pod_pending': False,
            'pod_compliant': True,
            'cod_collected': True,
            'hard_copy_confirmation': {'required': True, 'pending': False},
        }
        wrong_hint = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'OA-0008',
            'capture_mode': 'hard_copy_confirmation',
        }
        hint = align_next_action_hint_with_workflow(wrong_hint, workflow, pod_cod)
        self.assertEqual(hint['action'], 'go_to_evidence_capture')
        self.assertEqual(hint['action_code'], 'OA-0010')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertFalse(hint.get('direct_execute'))

    def test_cod_at_delivery_hints_unloading_before_collect_payment(self):
        shipment = SimpleNamespace(shipment_status='At Delivery')
        from unittest.mock import patch

        with patch(
            'mobile_api.utils.next_action_hint_builder.shipment_delivery_arrival_done',
            return_value=True,
        ):
            hint = build_next_action_hint(
                workflow={
                    'allowed_actions': [
                        {
                            'action_code': 'OA-0007',
                            'english_label': 'Start Unloading',
                        },
                        {
                            'action_code': 'OA-0009',
                            'english_label': 'Collect Payment',
                            'execution_requirements': {'auto_treasury_post': True},
                        },
                    ],
                    'next_action': {'action_code': 'OA-0009'},
                },
                pod_cod={
                    'pod_pending': True,
                    'pod_compliant': False,
                    'cod_collected': False,
                    'cod_pending': False,
                },
                order_type='COD',
                shipment=shipment,
            )
            self.assertEqual(hint['action_code'], 'OA-0007')
            self.assertEqual(hint['action'], 'go_to_evidence_capture')
            self.assertFalse(hint.get('direct_execute'))

    def test_in_transit_hints_delivery_arrival_before_unloading(self):
        shipment = SimpleNamespace(shipment_status='In Transit')
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0006',
                        'english_label': 'Delivery Arrival',
                        'shipment_status_impact': 'At_Delivery',
                    },
                    {
                        'action_code': 'OA-0007',
                        'english_label': 'Start Unloading',
                    },
                ],
                'next_action': {'action_code': 'OA-0007'},
            },
            pod_cod={'pod_pending': True, 'pod_compliant': False},
            order_type='COD',
            shipment=shipment,
        )
        self.assertEqual(hint['action_code'], 'OA-0006')
        self.assertEqual(hint['action'], 'go_to_evidence_capture')

    def test_loaded_column_hints_delivery_arrival_after_departure_log(self):
        from unittest.mock import patch

        shipment = SimpleNamespace(shipment_status='Loaded')
        with patch(
            'mobile_api.utils.next_action_hint_builder.shipment_delivery_arrival_done',
            return_value=False,
        ), patch(
            'mobile_api.utils.next_action_hint_builder.shipment_at_or_past_in_transit',
            return_value=True,
        ):
            hint = build_next_action_hint(
                workflow={
                    'allowed_actions': [
                        {
                            'action_code': 'OA-0020',
                            'english_label': 'Delivery Arrival',
                        },
                    ],
                    'next_action': {'action_code': 'OA-0020'},
                },
                pod_cod={'pod_pending': False, 'pod_compliant': False},
                order_type='Credit',
                shipment=shipment,
            )
        self.assertEqual(hint['action_code'], 'OA-0020')
        self.assertEqual(hint['action'], 'go_to_evidence_capture')

    def test_loaded_column_hints_delivery_arrival_with_empty_allowed_actions(self):
        from unittest.mock import patch

        shipment = SimpleNamespace(shipment_status='Loaded')
        with patch(
            'mobile_api.utils.next_action_hint_builder.shipment_delivery_arrival_done',
            return_value=False,
        ), patch(
            'mobile_api.utils.next_action_hint_builder.shipment_at_or_past_in_transit',
            return_value=True,
        ), patch(
            'mobile_api.utils.next_action_hint_builder.resolve_delivery_arrival_action_code_from_context',
            return_value='OA-0020',
        ):
            hint = build_next_action_hint(
                workflow={
                    'allowed_actions': [],
                    'next_action': {},
                },
                pod_cod={'pod_pending': False, 'pod_compliant': False},
                order_type='Credit',
                shipment=shipment,
                tenant_schema='tenant_demo',
            )
        self.assertEqual(hint['action_code'], 'OA-0020')
        self.assertEqual(hint['action'], 'go_to_evidence_capture')

    def test_cod_doc_gate_pod_pending_does_not_hint_pod_after_departure(self):
        """Missing shipment document must not surface POD before delivery milestones."""
        from unittest.mock import patch

        shipment = SimpleNamespace(shipment_status='Loaded')
        with patch(
            'mobile_api.utils.next_action_hint_builder.shipment_delivery_arrival_done',
            return_value=False,
        ), patch(
            'mobile_api.utils.next_action_hint_builder.shipment_at_or_past_in_transit',
            return_value=True,
        ), patch(
            'mobile_api.utils.next_action_hint_builder._delivery_arrival_step_due',
            return_value=False,
        ), patch(
            'mobile_api.utils.next_action_hint_builder._pod_upload_step_due',
            return_value=False,
        ):
            hint = build_next_action_hint(
                workflow={
                    'allowed_actions': [
                        {
                            'action_code': 'OA-0009',
                            'english_label': 'POD',
                            'execution_requirements': {'auto_pod_post': True},
                        },
                    ],
                    'next_action': {},
                },
                pod_cod={
                    'pod_pending': True,
                    'pod_compliant': False,
                    'shipment_document_message': 'Shipment Document missing.',
                },
                order_type='COD',
                shipment=shipment,
            )
        self.assertNotEqual(hint.get('action'), 'go_to_pod_capture')
        self.assertEqual(hint.get('action'), 'refresh_job_detail')

    def test_pod_capture_after_unloading_when_prior_pod_log_invalid(self):
        shipment = SimpleNamespace(shipment_status='At Delivery')
        from unittest.mock import patch

        with patch(
            'mobile_api.utils.next_action_hint_builder.shipment_pod_prerequisites_done',
            return_value=True,
        ), patch(
            'mobile_api.utils.next_action_hint_builder.shipment_pod_upload_log_is_valid',
            return_value=False,
        ), patch(
            'mobile_api.utils.next_action_hint_builder.shipment_delivery_arrival_done',
            return_value=True,
        ), patch(
            'mobile_api.utils.next_action_hint_builder.shipment_unloading_done',
            return_value=True,
        ), patch(
            'mobile_api.utils.next_action_hint_builder.shipment_unloading_completed_done',
            return_value=True,
        ):
            hint = build_next_action_hint(
                workflow={
                    'allowed_actions': [
                        {
                            'action_code': 'OA-0008',
                            'english_label': 'POD',
                            'execution_requirements': {'auto_pod_post': True},
                        },
                    ],
                    'next_action': {'action_code': 'OA-0009'},
                },
                pod_cod={
                    'pod_pending': True,
                    'pod_compliant': False,
                    'digital_evidence_complete': False,
                },
                order_type='COD',
                shipment=shipment,
            )
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['action_code'], 'OA-0008')

    def test_cod_collect_payment_next_redirects_to_pod_when_pending(self):
        shipment = SimpleNamespace(shipment_status='At Delivery')
        with self.subTest('after_unloading'):
            from unittest.mock import patch

            with patch(
                'mobile_api.utils.next_action_hint_builder.shipment_unloading_done',
                return_value=True,
            ), patch(
                'mobile_api.utils.next_action_hint_builder.shipment_delivery_arrival_done',
                return_value=True,
            ), patch(
                'mobile_api.utils.next_action_hint_builder.shipment_pod_prerequisites_done',
                return_value=True,
            ), patch(
                'mobile_api.utils.next_action_hint_builder.shipment_pod_upload_log_is_valid',
                return_value=False,
            ):
                hint = build_next_action_hint(
                    workflow={
                        'allowed_actions': [
                            {
                                'action_code': 'OA-0008',
                                'execution_requirements': {'auto_pod_post': True},
                            },
                            {
                                'action_code': 'OA-0009',
                                'execution_requirements': {'auto_treasury_post': True},
                            },
                        ],
                        'next_action': {'action_code': 'OA-0009'},
                    },
                    pod_cod={'pod_pending': True, 'cod_collected': False},
                    order_type='COD',
                    shipment=shipment,
                )
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['action_code'], 'OA-0008')

    def test_align_redirects_collect_payment_to_unloading_at_delivery(self):
        shipment = SimpleNamespace(shipment_status='At Delivery')
        workflow = {
            'allowed_actions': [
                {'action_code': 'OA-0007', 'english_label': 'Start Unloading'},
                {
                    'action_code': 'OA-0009',
                    'english_label': 'Collect Payment',
                    'execution_requirements': {'auto_treasury_post': True},
                },
            ],
            'primary_action': {
                'action_code': 'OA-0009',
                'execution_requirements': {'auto_treasury_post': True},
            },
        }
        pod_cod = {
            'pod_pending': False,
            'pod_compliant': False,
            'cod_collected': False,
        }
        wrong_hint = {
            'action': 'go_to_payment_collection',
            'screen': 'collect_payment',
            'action_code': 'OA-0009',
        }
        hint = align_next_action_hint_with_workflow(
            wrong_hint,
            workflow,
            pod_cod,
            shipment=shipment,
        )
        self.assertEqual(hint['action_code'], 'OA-0007')
        self.assertEqual(hint['action'], 'go_to_evidence_capture')

    def test_align_keeps_pod_capture_when_end_job_in_allowed_and_pod_pending(self):
        workflow = {
            'primary_action': {
                'action_code': 'OA-0009',
                'action_label': 'POD',
                'action': 'go_to_pod_capture',
                'capture_ui': {
                    'primary_button': {
                        'label': 'Next',
                        'execute_action_code': 'OA-0009',
                    },
                },
            },
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
        hint = align_next_action_hint_with_workflow(hint_in, workflow, pod_cod)
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['action_code'], 'OA-0009')
        self.assertTrue(hint.get('show_pod_capture_button'))

    def test_align_collect_payment_hint_stays_on_timeline_when_pod_complete(self):
        shipment = SimpleNamespace(shipment_status='POD Submitted')
        workflow = {
            'allowed_actions': [
                {
                    'action_code': 'OA-0009',
                    'english_label': 'Collect Payment',
                    'execution_requirements': {'auto_treasury_post': True},
                },
            ],
            'primary_action': {
                'action_code': 'OA-0009',
                'execution_requirements': {'auto_treasury_post': True},
            },
        }
        pod_cod = {
            'pod_pending': False,
            'pod_compliant': True,
            'cod_collected': False,
        }
        wrong_hint = {
            'action': 'go_to_payment_collection',
            'screen': 'collect_payment',
            'action_code': 'OA-0009',
        }
        hint = align_next_action_hint_with_workflow(
            wrong_hint,
            workflow,
            pod_cod,
            shipment=shipment,
        )
        self.assertEqual(hint['action_code'], 'OA-0009')
        self.assertEqual(hint['screen'], 'collect_payment')
        self.assertEqual(hint['action'], 'go_to_payment_collection')

    def test_align_back_from_hard_pod_prefers_hard_copy_over_collect_payment(self):
        """COD round-trip leg 2: back navigation must not skip hard-copy confirmation."""
        shipment = SimpleNamespace(shipment_status='POD Submitted', order_type='COD')
        workflow = {
            'allowed_actions': [
                {
                    'action_code': 'OA-0009',
                    'english_label': 'Collect Payment',
                    'execution_requirements': {'auto_treasury_post': True},
                },
                {
                    'action_code': 'OA-0008',
                    'english_label': 'POD',
                    'action': 'go_to_pod_capture',
                    'capture_mode': 'hard_copy_confirmation',
                    'execution_requirements': {
                        'auto_pod_post': True,
                        'hard_copy_collection': True,
                    },
                },
            ],
            'primary_action': {
                'action_code': 'OA-0009',
                'execution_requirements': {'auto_treasury_post': True},
            },
        }
        pod_cod = {
            'pod_pending': False,
            'pod_compliant': True,
            'hard_pod_pending': True,
            'cod_collected': False,
            'hard_copy_confirmation': {
                'applicable': True,
                'required': True,
                'actionable': True,
                'execute_action_code': 'OA-0008',
            },
            'capture_steps': ['digital_evidence', 'hard_copy_confirmation'],
            'compliance_integrity': {
                'log_evidence': {'pod_uploaded': True},
            },
        }
        wrong_hint = {
            'action': 'go_to_payment_collection',
            'screen': 'collect_payment',
            'action_code': 'OA-0009',
        }
        hint = align_next_action_hint_with_workflow(
            wrong_hint,
            workflow,
            pod_cod,
            shipment=shipment,
        )
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint.get('capture_mode'), 'hard_copy_confirmation')

    def test_cod_collect_payment_on_job_detail_opens_payment_screen(self):
        shipment = SimpleNamespace(shipment_status='POD Submitted')
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0009',
                        'execution_requirements': {'auto_treasury_post': True},
                    },
                ],
                'next_action': {'action_code': 'OA-0009'},
            },
            pod_cod={
                'pod_pending': False,
                'pod_compliant': True,
                'cod_collected': False,
            },
            order_type='COD',
            shipment=shipment,
        )
        self.assertEqual(hint['action_code'], 'OA-0009')
        self.assertEqual(hint['screen'], 'collect_payment')
        self.assertEqual(hint['action'], 'go_to_payment_collection')
        self.assertFalse(hint.get('pod_submitted'))

    def test_cod_collect_payment_after_pod_execute_stays_on_timeline(self):
        shipment = SimpleNamespace(shipment_status='POD Submitted')
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0009',
                        'execution_requirements': {'auto_treasury_post': True},
                    },
                ],
                'next_action': {'action_code': 'OA-0009'},
            },
            pod_cod={
                'pod_pending': False,
                'pod_compliant': True,
                'cod_collected': False,
            },
            action_code='OA-0008',
            order_type='COD',
            shipment=shipment,
        )
        self.assertEqual(hint['action_code'], 'OA-0009')
        self.assertEqual(hint['screen'], 'job_detail')
        self.assertEqual(hint['action'], 'refresh_job_detail')
        self.assertTrue(hint.get('pod_submitted'))

    def test_empty_move_complete_redirects_to_dashboard(self):
        movement = SimpleNamespace(status='Completed')
        hint = build_next_action_hint(
            workflow={'workflow_status': [
                {'step_key': 'pickup', 'completed': True},
                {'step_key': 'in_transit', 'completed': True},
                {'step_key': 'delivery', 'completed': True},
                {'step_key': 'complete', 'completed': True},
            ]},
            pod_cod={},
            action_code='EM4',
            movement=movement,
            tenant_schema='tenant_a',
        )
        self.assertEqual(hint['action'], 'go_to_dashboard')
        self.assertEqual(hint['screen'], 'dashboard')
        self.assertTrue(hint['show_completion_screen'])

    def test_empty_move_active_returns_evidence_capture_hint(self):
        movement = SimpleNamespace(status='In Progress')
        hint = build_next_action_hint(
            workflow={
                'workflow_metadata': {'entity_type': 'movement', 'job_type': 'movement'},
                'allowed_actions': [
                    {
                        'action_code': 'OA-0014',
                        'execution_label': 'Start Movement',
                        'execution_requirements': {'sequence_category': 'empty_move'},
                    },
                ],
                'next_action': {'action_code': 'OA-0014'},
                'primary_action': {'action_code': 'OA-0014'},
            },
            pod_cod={},
            movement=movement,
            tenant_schema='tenant_a',
        )
        self.assertEqual(hint['action'], 'go_to_evidence_capture')
        self.assertEqual(hint['screen'], 'evidence_capture')
        self.assertEqual(hint['action_code'], 'OA-0014')
        self.assertEqual(hint.get('ui_mode'), 'empty_move')
        self.assertTrue(hint.get('requires_evidence_capture'))
        self.assertTrue(hint.get('capture_ui'))
