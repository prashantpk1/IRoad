"""Unit tests for next_action_hint builder."""
from __future__ import annotations

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

    def test_after_a10_execute_go_dashboard(self):
        hint = build_next_action_hint(
            workflow={'allowed_actions': [], 'next_action': {}},
            pod_cod={},
            action_code='A10',
            order_type='Credit',
        )
        self.assertTrue(hint['job_closed'])
        self.assertEqual(hint['action'], 'go_to_dashboard')

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
