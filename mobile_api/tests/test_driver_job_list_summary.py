"""
Tests for driver job list summary counters API.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.helpers.job_list_aggregations import (
    job_list_movement_counter_filters,
    job_list_shipment_counter_filters,
    shipment_cancelled_tab_filter_q,
    shipment_completed_tab_filter_q,
)
from mobile_api.services.driver_job_list_counters import (
    build_job_list_counters,
    project_job_list_summary_counters,
)


class JobListAggregationFilterTests(SimpleTestCase):
    def test_shipment_counter_filter_keys(self):
        filters = job_list_shipment_counter_filters(
            pod_compliant='Compliant',
            collection_pending='Pending',
        )
        self.assertEqual(
            set(filters.keys()),
            {
                'active_shipments',
                'completed_shipments',
                'cancelled_shipments',
                'pod_pending',
                'cod_pending',
            },
        )

    def test_movement_counter_filter_keys(self):
        filters = job_list_movement_counter_filters()
        self.assertEqual(
            set(filters.keys()),
            {
                'active_movements',
                'completed_movements',
                'cancelled_movements',
            },
        )

    def test_completed_and_cancelled_q_build(self):
        self.assertIn('Delivered', str(shipment_completed_tab_filter_q()))
        self.assertIn('Cancelled', str(shipment_cancelled_tab_filter_q()))


class JobListCounterProjectionTests(SimpleTestCase):
    def test_project_merges_shipment_and_movement(self):
        out = project_job_list_summary_counters(
            {
                'active_shipments': 3,
                'completed_shipments': 10,
                'cancelled_shipments': 1,
                'pod_pending': 2,
                'cod_pending': 1,
            },
            {
                'active_movements': 4,
                'completed_movements': 8,
                'cancelled_movements': 0,
            },
        )
        self.assertEqual(out['active_shipments'], 3)
        self.assertEqual(out['completed_movements'], 8)
        self.assertEqual(out['pod_pending'], 2)
        self.assertEqual(len(out), 8)


class JobListCounterAggregateTests(SimpleTestCase):
    def test_build_job_list_counters_composes_aggregates(self):
        driver = MagicMock()
        driver.pk = uuid4()

        from mobile_api.services import driver_job_list_counters as mod

        with patch.object(
            mod,
            'aggregate_job_list_shipment_counters',
            return_value={
                'active_shipments': 1,
                'completed_shipments': 2,
                'cancelled_shipments': 0,
                'pod_pending': 1,
                'cod_pending': 0,
            },
        ), patch.object(
            mod,
            'aggregate_job_list_movement_counters',
            return_value={
                'active_movements': 3,
                'completed_movements': 4,
                'cancelled_movements': 1,
            },
        ):
            counters = build_job_list_counters(driver=driver)

        self.assertEqual(len(counters), 8)
        self.assertEqual(counters['completed_shipments'], 2)
        self.assertEqual(counters['cancelled_movements'], 1)
