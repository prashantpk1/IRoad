"""Tests for tenant-scoped COD / job-close action resolution."""
from __future__ import annotations

from unittest import TestCase

from mobile_api.helpers.job_action_resolver import (
    row_is_collect_payment_action,
    row_is_job_close_action,
    row_is_unloading_action,
    resolve_collect_payment_action_code_from_context,
    resolve_job_close_action_code_from_context,
    resolve_unloading_action_code_from_context,
)

class JobActionResolverTests(TestCase):
    def test_row_is_collect_payment_action_from_requirements(self):
        self.assertTrue(
            row_is_collect_payment_action(
                {
                    'action_code': 'OA-0009',
                    'execution_requirements': {'auto_treasury_post': True},
                },
            ),
        )

    def test_resolve_collect_payment_code_from_workflow(self):
        code = resolve_collect_payment_action_code_from_context(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0009',
                        'execution_requirements': {'auto_treasury_post': True},
                    },
                ],
                'next_action': {'action_code': 'OA-0009'},
            },
            next_code='OA-0009',
        )
        self.assertEqual(code, 'OA-0009')

    def test_row_is_job_close_action(self):
        self.assertTrue(
            row_is_job_close_action(
                {
                    'action_code': 'OA-0010',
                    'execution_label': 'Job Closed',
                },
            ),
        )

    def test_resolve_job_close_code_from_workflow(self):
        code = resolve_job_close_action_code_from_context(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'OA-0010',
                        'execution_label': 'Job Closed',
                        'execution_requirements': {
                            'shipment_status_impact': 'Closed',
                        },
                    },
                ],
                'next_action': {'action_code': 'OA-0010'},
            },
            next_code='OA-0010',
        )
        self.assertEqual(code, 'OA-0010')

    def test_collect_payment_fallback_label(self):
        self.assertTrue(
            row_is_collect_payment_action(
                {
                    'action_code': 'OA-0099',
                    'english_label': 'Collect Payment COD',
                },
            ),
        )

    def test_row_is_unloading_action_by_label_not_legacy_code(self):
        self.assertTrue(
            row_is_unloading_action(
                {
                    'action_code': 'CUSTOM-UNLOAD-99',
                    'english_label': 'Start Unloading',
                },
            ),
        )

    def test_resolve_unloading_code_from_workflow(self):
        code = resolve_unloading_action_code_from_context(
            workflow={
                'allowed_actions': [
                    {
                        'action_code': 'CUSTOM-UNLOAD-99',
                        'english_label': 'Start Unloading',
                    },
                ],
                'next_action': {'action_code': 'CUSTOM-UNLOAD-99'},
            },
            next_code='CUSTOM-UNLOAD-99',
        )
        self.assertEqual(code, 'CUSTOM-UNLOAD-99')

    def test_row_is_job_close_action_by_impact_not_code(self):
        self.assertTrue(
            row_is_job_close_action(
                {
                    'action_code': 'CUSTOM-CLOSE-99',
                    'execution_requirements': {
                        'shipment_status_impact': 'Closed',
                    },
                },
            ),
        )
