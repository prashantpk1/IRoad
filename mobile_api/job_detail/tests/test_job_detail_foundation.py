"""
Foundation tests — orchestration wiring and response contract shape only.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.dto.job_detail_response_builder import (
    JobDetailResponseBuilder,
)
from mobile_api.job_detail.services.job_detail_context_service import (
    JobDetailContextService,
)


class JobDetailFoundationTests(SimpleTestCase):
    def test_response_contract_keys(self):
        context = JobDetailContext(
            driver=object(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type='shipment',
            job_id='ship-1',
        )
        payload = JobDetailResponseBuilder().build(context)
        self.assertEqual(
            set(payload.keys()),
            {
                'job',
                'workflow',
                'timeline',
                'pod_cod',
                'round_trip',
                'alerts',
                'sync_metadata',
                'operational_issues',
                'support_actions',
                'unresolved_issue_count',
                'blocking_recommendation',
                'next_action_hint',
            },
        )

    def test_movement_omits_pod_cod_and_round_trip_in_builder(self):
        context = JobDetailContext(
            driver=object(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type='movement',
            job_id='mov-1',
            pod_cod={'pod_pending': True},
            round_trip={'booking_id': 'x'},
        )
        payload = JobDetailResponseBuilder().build(context)
        self.assertEqual(payload['pod_cod'], {})
        self.assertEqual(payload['round_trip'], {})

    def test_normalize_job_type_aliases(self):
        svc = JobDetailContextService()
        self.assertEqual(svc._normalize_job_type('empty_move'), 'movement')
        self.assertEqual(svc._normalize_job_type('SHIPMENT'), 'shipment')
        self.assertEqual(svc._normalize_job_type('booking'), 'booking')

    def test_invalid_job_type_raises(self):
        svc = JobDetailContextService()
        with self.assertRaises(ValueError):
            svc._normalize_job_type('warehouse')
