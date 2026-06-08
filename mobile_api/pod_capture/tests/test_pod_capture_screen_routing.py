"""POD capture GET screen routing tests."""
from __future__ import annotations

from unittest import TestCase

from mobile_api.pod_capture.services.pod_capture_screen_routing import (
    HARD_COPY_CONFIRMATION_SCREEN,
    POD_CAPTURE_SCREEN,
    build_pod_capture_get_routing,
)


class PodCaptureScreenRoutingTests(TestCase):
    def test_routes_to_hard_copy_when_pending(self):
        routing = build_pod_capture_get_routing(
            {
                'hard_pod_pending': True,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
                    'execute_action_code': 'A7H',
                    'pages': [{'label': 'Page 1'}],
                },
            }
        )
        self.assertEqual(routing['screen'], HARD_COPY_CONFIRMATION_SCREEN)
        self.assertEqual(routing['action_code'], 'A7H')

    def test_routes_to_digital_evidence_by_default(self):
        routing = build_pod_capture_get_routing(
            {
                'hard_pod_pending': False,
                'hard_copy_confirmation': {'required': False, 'pending': False},
            }
        )
        self.assertEqual(routing['screen'], POD_CAPTURE_SCREEN)
        self.assertEqual(routing['action_code'], 'A7')

    def test_step_query_forces_hard_copy_screen(self):
        routing = build_pod_capture_get_routing(
            {
                'hard_pod_pending': False,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': False,
                    'execute_action_code': 'A7H',
                },
            },
            requested_step='hard_copy_confirmation',
        )
        self.assertEqual(routing['screen'], HARD_COPY_CONFIRMATION_SCREEN)
