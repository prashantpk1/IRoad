"""Unit tests for next_action_hint builder."""
from __future__ import annotations

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from mobile_api.utils.next_action_hint_builder import build_next_action_hint


class NextActionHintBuilderTests(SimpleTestCase):
    def test_a10_next_shows_close_job(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [{'action_code': 'A10'}],
                'next_action': {'action_code': 'A10'},
            },
            pod_cod={'pod_compliant': True, 'pod_pending': False},
            order_type='Credit',
        )
        self.assertEqual(hint['action_code'], 'A10')
        self.assertEqual(hint['action'], 'execute_action')
        self.assertTrue(hint.get('show_close_job_button'))

    def test_cod_payment_complete_pod_submitted_shows_close_job_without_workflow_a10(
        self,
    ):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [],
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
        self.assertEqual(hint['action_code'], 'A10')
        self.assertTrue(hint.get('show_close_job_button'))

    def test_after_a10_execute_go_dashboard(self):
        hint = build_next_action_hint(
            workflow={'allowed_actions': [], 'next_action': {}},
            pod_cod={},
            action_code='A10',
            order_type='Credit',
        )
        self.assertTrue(hint['job_closed'])
        self.assertEqual(hint['action'], 'go_to_dashboard')

    def test_after_a10_round_trip_outbound_hints_open_return_job(self):
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
            workflow={'allowed_actions': [], 'next_action': {}},
            pod_cod={},
            action_code='A10',
            order_type='Credit',
            booking=booking,
            driver=driver,
        )
        self.assertEqual(hint['action'], 'go_to_dashboard')
        self.assertTrue(hint.get('booking_continues'))
        self.assertTrue(hint.get('leg_completed'))
        open_job = hint.get('open_job') or {}
        self.assertEqual(open_job.get('job_type'), 'booking')
        self.assertEqual(open_job.get('job_id'), 'bk-round-1')
        self.assertEqual(open_job.get('booking_item_type'), 'Backload')
        self.assertTrue(open_job.get('backload_bootstrap_pending'))

    def test_a1_hint_direct_execute(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [{'action_code': 'A1'}],
                'next_action': {'action_code': 'A1'},
            },
        )
        self.assertEqual(hint['action_code'], 'A1')
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

    def test_after_a7_routes_to_hard_copy_before_a8(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [{'action_code': 'A8'}],
                'next_action': {'action_code': 'A8'},
            },
            pod_cod={
                'hard_pod_pending': True,
                'pod_pending': False,
                'pod_compliant': False,
                'hard_copy_confirmation': {'required': True, 'pending': True},
            },
            action_code='A7',
            order_type='COD',
        )
        self.assertEqual(hint['action_code'], 'A7H')
        self.assertEqual(hint['action'], 'go_to_pod_capture')
        self.assertEqual(hint['capture_mode'], 'hard_copy_confirmation')

    def test_a8_only_when_hard_copy_complete(self):
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [{'action_code': 'A8'}],
                'next_action': {'action_code': 'A8'},
            },
            pod_cod={
                'hard_pod_pending': False,
                'pod_pending': False,
                'pod_compliant': True,
            },
            order_type='COD',
        )
        self.assertEqual(hint['action_code'], 'A8')
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
                'allowed_actions': [{'action_code': 'A7H'}],
                'next_action': {'action_code': 'A7H'},
            },
            pod_cod={
                'hard_pod_pending': True,
                'pod_pending': False,
                'hard_copy_confirmation': {'required': True, 'pending': True},
            },
            order_type='COD',
        )
        self.assertEqual(hint['action_code'], 'A7H')
        self.assertEqual(hint['screen'], 'pod_capture')
        self.assertEqual(hint['capture_mode'], 'hard_copy_confirmation')
