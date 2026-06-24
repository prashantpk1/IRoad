"""Unit tests for next_action_hint builder."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

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
            },
            pod_cod={'pod_compliant': True, 'pod_pending': False},
            order_type='Credit',
        )
        self.assertEqual(hint['action_code'], 'OA-0010')
        self.assertEqual(hint['action'], 'execute_action')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertTrue(hint.get('direct_execute'))

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
        self.assertEqual(hint['action'], 'execute_action')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertTrue(hint.get('direct_execute'))
        self.assertTrue(hint.get('payment_collected'))

    def test_round_trip_outbound_pod_complete_shows_continue_not_close(self):
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
        booking.shipments = MagicMock()
        booking.shipments.all.return_value = [outbound]

        driver = MagicMock()
        driver.pk = 'drv-1'

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
        self.assertEqual(hint['action_code'], 'OA-0010')
        self.assertEqual(hint['action'], 'execute_action')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertTrue(hint.get('direct_execute'))
        self.assertFalse(hint.get('booking_continues'))
        self.assertFalse(hint.get('leg_completed'))

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
        self.assertEqual(hint['action'], 'execute_action')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertTrue(hint.get('direct_execute'))

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
        self.assertEqual(hint['action'], 'go_to_dashboard')
        self.assertFalse(hint['job_closed'])
        self.assertTrue(hint.get('booking_continues'))
        self.assertTrue(hint.get('leg_completed'))
        open_job = hint.get('open_job') or {}
        self.assertEqual(open_job.get('job_type'), 'booking')
        self.assertEqual(open_job.get('job_id'), 'bk-round-1')
        self.assertEqual(open_job.get('booking_item_type'), 'Backload')
        self.assertTrue(open_job.get('backload_bootstrap_pending'))

    def test_start_job_hint_direct_execute(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [_START_JOB_ROW],
                'next_action': {'action_code': 'OA-0001'},
            },
        )
        self.assertEqual(hint['action_code'], 'OA-0001')
        self.assertEqual(hint['action'], 'execute_action')
        self.assertTrue(hint.get('direct_execute'))
        self.assertFalse(hint.get('requires_evidence_capture', True))

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

    def test_after_pod_routes_to_hard_copy_before_unloading(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [_UNLOADING_ROW],
                'next_action': {'action_code': 'OA-0007'},
            },
            pod_cod={
                'hard_pod_pending': True,
                'pod_pending': False,
                'pod_compliant': False,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
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
        self.assertEqual(hint['action'], 'execute_action')

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
                'delivery_blocked': True,
                'cod_collected': True,
                'hard_copy_confirmation': {'required': True, 'pending': True},
            },
            order_type='COD',
        )
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['capture_mode'], 'hard_copy_confirmation')
        self.assertNotEqual(hint['action'], 'wait_for_ops')

    def test_hard_pod_pending_routes_capture_only_for_a7h_next(self):
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
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
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

    def test_hard_pod_type_routes_digital_before_hard_copy(self):
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

    def test_oa_0010_close_hint_direct_execute_no_evidence(self):
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
        self.assertEqual(hint['action'], 'execute_action')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertTrue(hint.get('direct_execute'))
        self.assertFalse(hint.get('requires_multipart'))

    def test_requires_multipart_false_for_direct_execute_start_job(self):
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
        self.assertEqual(hint['action'], 'execute_action')
        self.assertEqual(hint['action_code'], 'OA-0010')
        self.assertTrue(hint.get('show_close_job_button'))
        self.assertTrue(hint.get('direct_execute'))

    def test_cod_at_delivery_hints_unloading_before_collect_payment(self):
        shipment = SimpleNamespace(shipment_status='At Delivery')
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
        self.assertEqual(hint['action'], 'execute_action')
        self.assertTrue(hint.get('direct_execute'))

    def test_cod_collect_payment_next_redirects_to_pod_when_pending(self):
        shipment = SimpleNamespace(shipment_status='At Delivery')
        with self.subTest('after_unloading'):
            from unittest.mock import patch

            with patch(
                'mobile_api.utils.next_action_hint_builder.shipment_unloading_done',
                return_value=True,
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
        self.assertEqual(hint['action'], 'execute_action')

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
