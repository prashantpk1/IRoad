"""
Tests for movement job list filters, status taxonomy, and card shape.
"""
from unittest.mock import MagicMock
from uuid import uuid4

from django.test import RequestFactory, SimpleTestCase

from mobile_api.helpers.job_list_filters import (
    JobListFilters,
    apply_job_filters,
    parse_movement_job_list_filters,
)
from mobile_api.helpers.operational_status import (
    MOVEMENT_CANCELLED_STATUSES,
    MOVEMENT_COMPLETED_STATUSES,
    movement_cancelled_filter_q,
    movement_completed_filter_q,
    movement_empty_move_filter_q,
    movement_tab_filter_q,
)
from mobile_api.services.driver_movement_list_service import build_movement_job_card
from mobile_api.helpers.job_card_projections import build_movement_job_card_projection


class MovementStatusTaxonomyTests(SimpleTestCase):
    def test_completed_and_cancelled_sets(self):
        self.assertIn('Completed', MOVEMENT_COMPLETED_STATUSES)
        self.assertIn('Cancelled', MOVEMENT_CANCELLED_STATUSES)

    def test_tab_filters_build(self):
        self.assertIsNotNone(movement_tab_filter_q('active').children)
        self.assertIsNotNone(movement_completed_filter_q().children)
        self.assertIsNotNone(movement_cancelled_filter_q().children)
        self.assertIsNotNone(movement_empty_move_filter_q().children)


class MovementJobListFilterParseTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _with_query_params(request):
        request.query_params = request.GET
        return request

    def test_locked_completed_tab(self):
        request = self._with_query_params(self.factory.get(
            '/api/v1/mobile/driver/jobs/movements/completed/',
            {'tab': 'active'},
        ))
        filters = parse_movement_job_list_filters(request, locked_tab='completed')
        self.assertEqual(filters.tab, 'completed')

    def test_empty_move_queue_locked(self):
        request = self._with_query_params(self.factory.get(
            '/api/v1/mobile/driver/jobs/movements/empty/',
        ))
        filters = parse_movement_job_list_filters(
            request,
            locked_tab='active',
            locked_queue='empty_move',
        )
        self.assertEqual(filters.queue, 'empty_move')


class MovementJobCardTests(SimpleTestCase):
    def test_empty_move_card_flags(self):
        movement = MagicMock()
        movement.movement_id = uuid4()
        movement.movement_no = 'MV-001'
        movement.status = 'Scheduled'
        movement.movement_source = 'empty'
        movement.empty_move_reason = 'Return to depot'
        movement.updated_at = None
        movement.created_at = None
        movement.movement_date = None
        movement.shipment = None
        movement.truck = None
        movement.from_location_point = None
        movement.to_location_point = None

        card = build_movement_job_card(movement, request=None)
        self.assertEqual(card['job_type'], 'movement')
        self.assertEqual(card['job_no'], 'MV-001')
        self.assertTrue(card['is_empty_move'])
        self.assertTrue(card['indicators']['is_empty_move'])
        # Delegates to same projection core
        card2 = build_movement_job_card_projection(movement, request=None)
        self.assertEqual(card['job_id'], card2['job_id'])


class MovementFilterQueryTests(SimpleTestCase):
    def test_movement_search_filter_query(self):
        from tenant_workspace.models import TenantTruckMovementLog
        from mobile_api.helpers.operational_status import driver_movement_scope_q

        driver = MagicMock()
        driver.pk = uuid4()
        driver.driver_id = driver.pk
        qs = TenantTruckMovementLog.objects.filter(driver_movement_scope_q(driver))
        filtered = apply_job_filters(
            qs,
            entity_type='movement',
            filters=JobListFilters(tab='all', search='MV-9'),
        )
        self.assertIn('movement_no', str(filtered.query))
