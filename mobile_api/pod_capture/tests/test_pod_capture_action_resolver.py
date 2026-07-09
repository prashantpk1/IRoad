"""Tests for tenant POD action code resolution."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE,
    CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE,
    action_code_is_digital_pod_upload,
    action_code_is_hard_copy_custody,
    find_allowed_action_row_by_impact,
    resolve_digital_pod_action_code_from_context,
    resolve_hard_copy_action_code_from_context,
    row_has_digital_pod_upload,
    row_has_hard_copy_collection,
)


class PodCaptureActionResolverTests(TestCase):
    def test_row_has_hard_copy_collection_by_flag(self):
        self.assertTrue(
            row_has_hard_copy_collection(
                {
                    'action_code': 'OA-0010',
                    'execution_requirements': {'hard_copy_collection': True},
                },
            ),
        )

    def test_row_has_digital_pod_upload_by_flag(self):
        self.assertTrue(
            row_has_digital_pod_upload(
                {
                    'action_code': 'OA-0008',
                    'execution_requirements': {'auto_pod_post': True},
                },
            ),
        )
        self.assertTrue(
            row_has_digital_pod_upload(
                {
                    'action_code': 'OA-0008',
                    'execution_requirements': {
                        'auto_pod_post': True,
                        'hard_copy_collection': True,
                    },
                },
            ),
        )
        self.assertFalse(
            row_has_digital_pod_upload(
                {
                    'action_code': 'OA-0010',
                    'execution_requirements': {'hard_copy_collection': True},
                },
            ),
        )

    def test_row_has_digital_pod_upload_by_english_label(self):
        self.assertTrue(
            row_has_digital_pod_upload(
                {
                    'action_code': 'OA-0099',
                    'english_label': 'POD',
                },
            ),
        )

    def test_row_has_digital_pod_upload_by_timeline_action_label(self):
        self.assertTrue(
            row_has_digital_pod_upload(
                {
                    'action_code': 'OA-0099',
                    'action_label': 'POD',
                },
            ),
        )

    def test_action_code_is_digital_pod_upload_from_workflow_row(self):
        workflow = {
            'allowed_actions': [
                {
                    'action_code': 'OA-0008',
                    'execution_requirements': {'auto_pod_post': True},
                },
            ],
        }
        self.assertTrue(
            action_code_is_digital_pod_upload('OA-0008', workflow=workflow),
        )

    def test_action_code_is_hard_copy_custody_from_workflow_row(self):
        workflow = {
            'allowed_actions': [
                {
                    'action_code': 'OA-0010',
                    'execution_requirements': {'hard_copy_collection': True},
                },
            ],
        }
        self.assertTrue(
            action_code_is_hard_copy_custody('OA-0010', workflow=workflow),
        )
        self.assertFalse(
            action_code_is_digital_pod_upload('OA-0010', workflow=workflow),
        )

    def test_find_pod_upload_row_in_timeline_pending(self):
        from mobile_api.pod_capture.services.pod_capture_action_resolver import (
            find_pod_upload_row_in_timeline,
        )

        row = find_pod_upload_row_in_timeline(
            {
                'timeline_preview': [
                    {
                        'action_code': 'OA-0009',
                        'action_label': 'POD',
                        'sequence_number': 9,
                        'is_performed': False,
                    },
                    {
                        'action_code': 'OA-0010',
                        'action_label': 'End Job',
                        'sequence_number': 10,
                        'is_performed': False,
                    },
                ],
            },
        )
        self.assertEqual(row.get('action_code'), 'OA-0009')

    def test_find_allowed_action_row_by_impact(self):
        row = find_allowed_action_row_by_impact(
            [
                {'action_code': 'OA-0008', 'execution_requirements': {'auto_pod_post': True}},
                {
                    'action_code': 'OA-0010',
                    'execution_requirements': {'hard_copy_collection': True},
                },
            ],
            'hard_copy_collection',
        )
        self.assertEqual(row.get('action_code'), 'OA-0010')

    def test_resolve_hard_copy_action_code_from_pod_cod_block(self):
        code = resolve_hard_copy_action_code_from_context(
            pod_cod={
                'hard_copy_confirmation': {
                    'execute_action_code': 'OA-0010',
                },
            },
        )
        self.assertEqual(code, 'OA-0010')

    def test_resolve_hard_copy_action_code_from_allowed_actions(self):
        code = resolve_hard_copy_action_code_from_context(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0010',
                        'execution_requirements': {'hard_copy_collection': True},
                    },
                ],
            },
        )
        self.assertEqual(code, 'OA-0010')

    def test_resolve_digital_action_code_from_allowed_actions(self):
        code = resolve_digital_pod_action_code_from_context(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0008',
                        'execution_requirements': {'auto_pod_post': True},
                    },
                ],
            },
        )
        self.assertEqual(code, 'OA-0008')

    @patch(
        'mobile_api.pod_capture.services.pod_capture_action_resolver.resolve_hard_copy_pod_action',
        return_value=SimpleNamespace(action_code='OA-0099'),
    )
    def test_resolve_hard_copy_action_code_from_tenant_master(self, _mock_action):
        code = resolve_hard_copy_action_code_from_context(tenant_schema='tenant_a')
        self.assertEqual(code, 'OA-0099')

    @patch(
        'mobile_api.pod_capture.services.pod_capture_action_resolver._iter_active_actions',
    )
    def test_resolve_digital_pod_action_includes_combined_upload_row(self, mock_iter):
        combined = SimpleNamespace(
            action_code='OA-0008',
            auto_pod_post=True,
            hard_copy_collection=True,
        )
        mock_iter.side_effect = lambda _schema: iter([combined])
        from mobile_api.pod_capture.services.pod_capture_action_resolver import (
            resolve_digital_pod_action,
            resolve_digital_pod_action_code,
        )

        self.assertIs(resolve_digital_pod_action('tenant_a'), combined)
        self.assertEqual(resolve_digital_pod_action_code('tenant_a'), 'OA-0008')

    def test_resolve_hard_copy_action_code_canonical_fallback(self):
        code = resolve_hard_copy_action_code_from_context()
        self.assertEqual(code, CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE)

    def test_resolve_digital_action_code_canonical_fallback(self):
        code = resolve_digital_pod_action_code_from_context()
        self.assertEqual(code, CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE)
