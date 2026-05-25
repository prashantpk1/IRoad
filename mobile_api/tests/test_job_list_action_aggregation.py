"""
Tests for batched latest-action and next-action job list architecture.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.helpers.job_list_action_aggregation import (
    annotate_shipment_list_latest_log_id,
    batch_fetch_latest_action_summaries,
    hydrate_job_list_page_actions,
    job_list_include_actions,
)
from mobile_api.helpers.job_list_next_action import (
    batch_build_shipment_next_action_hints,
    build_movement_next_action_hint,
    build_shipment_next_action_hint,
)


class JobListActionAggregationTests(SimpleTestCase):
    def test_include_actions_query_override(self):
        factory = __import__('django.test', fromlist=['RequestFactory']).RequestFactory()
        request = factory.get('/', {'include_actions': '0'})
        request.query_params = request.GET
        self.assertFalse(job_list_include_actions(request))

    def test_shipment_queryset_annotation(self):
        from tenant_workspace.models import TenantShipment

        driver = MagicMock()
        driver.pk = uuid4()
        qs = TenantShipment.objects.all()
        annotated = annotate_shipment_list_latest_log_id(qs, driver=driver)
        self.assertIn('latest_action_log_id', str(annotated.query))

    def test_batch_fetch_empty_ids(self):
        self.assertEqual(batch_fetch_latest_action_summaries([]), {})

    def test_hydrate_attaches_summaries_without_per_row_fetch(self):
        shipment = MagicMock()
        shipment.shipment_id = uuid4()
        shipment.pk = shipment.shipment_id
        shipment.shipment_status = 'In Transit'
        shipment.order_type = ''
        shipment.pod_status = 'Compliant'
        shipment.collection_status = 'Collected'
        shipment.cod_amount = 0
        shipment.latest_action_log_id = None

        with patch(
            'mobile_api.helpers.job_list_action_aggregation.batch_fetch_latest_action_by_shipment_ids',
            return_value={},
        ) as mock_fetch:
            hydrate_job_list_page_actions(
                [shipment],
                entity_type='shipment',
                driver=MagicMock(pk=uuid4()),
                include_actions=True,
            )
            mock_fetch.assert_called_once()

        self.assertTrue(hasattr(shipment, '_job_list_next_action_hint'))

    def test_next_action_hints_are_in_memory(self):
        shipment = MagicMock()
        shipment.shipment_id = uuid4()
        shipment.shipment_status = 'At Delivery'
        shipment.order_type = ''
        shipment.pod_status = 'Compliant'
        shipment.collection_status = 'Collected'
        shipment.cod_amount = 0

        with patch(
            'mobile_api.services.driver_dashboard_current_job.build_next_action_hint',
            return_value='Deliver',
        ):
            hints = batch_build_shipment_next_action_hints([shipment])
        self.assertEqual(hints[str(shipment.shipment_id)], 'Deliver')

    def test_movement_hint_without_shipment(self):
        movement = MagicMock()
        movement.status = 'Scheduled'
        movement.shipment = None
        hint = build_movement_next_action_hint(movement)
        self.assertIsNotNone(hint)
