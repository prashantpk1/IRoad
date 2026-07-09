"""POD capture GET screen routing tests."""
from __future__ import annotations

from unittest import TestCase

from mobile_api.pod_capture.services.pod_capture_screen_routing import (
    HARD_COPY_CONFIRMATION_SCREEN,
    POD_CAPTURE_SCREEN,
    build_pod_capture_get_routing,
)
from mobile_api.pod_capture.services.pod_section_metadata import (
    HARD_COPY_SCREEN_TITLE,
    UI_MODE_HARD_POD_CONFIRMATION,
    UI_MODE_DIGITAL_EVIDENCE,
)


class PodCaptureScreenRoutingTests(TestCase):
    def test_starts_digital_when_hard_pending_but_digital_not_complete(self):
        routing = build_pod_capture_get_routing(
            {
                'hard_pod_pending': True,
                'digital_evidence_complete': False,
                'capture_steps': ['digital_evidence', 'hard_copy_confirmation'],
                'hard_copy_confirmation': {
                    'applicable': True,
                    'required': True,
                    'pending': True,
                    'actionable': True,
                    'execute_action_code': 'A7H',
                    'pages': [{'label': 'Page 1'}],
                },
            }
        )
        self.assertEqual(routing['capture_mode'], UI_MODE_DIGITAL_EVIDENCE)
        self.assertEqual(routing['action_code'], 'A7')
        self.assertEqual(routing['pod_capture_steps'], ['digital_evidence', 'hard_copy_confirmation'])

    def test_resumes_hard_copy_when_digital_complete(self):
        routing = build_pod_capture_get_routing(
            {
                'hard_pod_pending': True,
                'digital_evidence_complete': True,
                'unloading_pending': False,
                'hard_copy_confirmation': {
                    'applicable': True,
                    'required': True,
                    'pending': True,
                    'actionable': True,
                    'execute_action_code': 'A7H',
                    'pages': [{'label': 'Page 1'}],
                },
            }
        )
        self.assertEqual(routing['screen'], POD_CAPTURE_SCREEN)
        self.assertEqual(routing['capture_mode'], HARD_COPY_CONFIRMATION_SCREEN)
        self.assertEqual(routing['action'], 'go_to_pod_capture')
        self.assertEqual(routing['action_code'], 'A7H')
        self.assertEqual(routing['screen_title'], HARD_COPY_SCREEN_TITLE)
        self.assertEqual(routing['ui_mode'], UI_MODE_HARD_POD_CONFIRMATION)

    def test_starts_digital_when_unloading_still_pending(self):
        routing = build_pod_capture_get_routing(
            {
                'hard_pod_pending': True,
                'digital_evidence_complete': True,
                'unloading_pending': True,
                'hard_copy_confirmation': {
                    'applicable': True,
                    'required': True,
                    'pending': True,
                    'execute_action_code': 'OA-0008',
                },
            }
        )
        self.assertEqual(routing['capture_mode'], UI_MODE_DIGITAL_EVIDENCE)
        self.assertEqual(routing['active_step'], 'digital_evidence')

    def test_stays_digital_when_document_gate_blocks_hard_copy(self):
        routing = build_pod_capture_get_routing(
            {
                'hard_pod_pending': True,
                'digital_evidence_complete': True,
                'unloading_pending': False,
                'hard_copy_confirmation': {
                    'applicable': True,
                    'required': True,
                    'pending': True,
                    'actionable': False,
                    'execute_action_code': 'A7H',
                    'pages': [],
                },
            }
        )
        self.assertEqual(routing['capture_mode'], UI_MODE_DIGITAL_EVIDENCE)
        self.assertEqual(routing['active_step'], 'digital_evidence')

    def test_routes_to_digital_evidence_by_default(self):
        routing = build_pod_capture_get_routing(
            {
                'hard_pod_pending': False,
                'hard_copy_confirmation': {'required': False, 'pending': False},
            }
        )
        self.assertEqual(routing['screen'], POD_CAPTURE_SCREEN)
        self.assertEqual(routing['action_code'], 'A7')
        self.assertEqual(routing['ui_mode'], UI_MODE_DIGITAL_EVIDENCE)

    def test_step_query_forces_hard_copy_screen_when_digital_complete(self):
        routing = build_pod_capture_get_routing(
            {
                'hard_pod_pending': True,
                'digital_evidence_complete': True,
                'unloading_pending': False,
                'hard_copy_confirmation': {
                    'required': True,
                    'pending': True,
                    'applicable': True,
                    'actionable': True,
                    'execute_action_code': 'A7H',
                },
            },
            requested_step='hard_copy_confirmation',
        )
        self.assertEqual(routing['screen'], POD_CAPTURE_SCREEN)
        self.assertEqual(routing['capture_mode'], HARD_COPY_CONFIRMATION_SCREEN)
