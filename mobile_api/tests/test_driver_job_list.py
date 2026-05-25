"""
Tests for driver job list module (scope, filters, ordering).
"""
from unittest.mock import MagicMock
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.helpers.job_list_filters import JobListFilters, apply_job_filters
from mobile_api.helpers.job_list_ordering import apply_job_ordering
from mobile_api.helpers.operational_status import (
    driver_movement_scope_q,
    driver_shipment_scope_q,
)
from mobile_api.services.driver_shipment_list_service import build_shipment_job_card


class JobListFilterTests(SimpleTestCase):
    def test_shipment_active_tab_filter_builds(self):
        from tenant_workspace.models import TenantShipment

        driver = MagicMock()
        driver.pk = uuid4()
        driver.driver_id = driver.pk
        qs = TenantShipment.objects.filter(driver_shipment_scope_q(driver))
        filtered = apply_job_filters(
            qs,
            entity_type='shipment',
            filters=JobListFilters(tab='active'),
        )
        self.assertIsNotNone(filtered.query)

    def test_movement_cancelled_tab_filter_builds(self):
        from tenant_workspace.models import TenantTruckMovementLog

        driver = MagicMock()
        driver.pk = uuid4()
        driver.driver_id = driver.pk
        qs = TenantTruckMovementLog.objects.filter(driver_movement_scope_q(driver))
        filtered = apply_job_filters(
            qs,
            entity_type='movement',
            filters=JobListFilters(tab='cancelled'),
        )
        self.assertIsNotNone(filtered.query)


class JobListOrderingTests(SimpleTestCase):
    def test_default_shipment_ordering(self):
        from tenant_workspace.models import TenantShipment

        qs = TenantShipment.objects.all()
        ordered = apply_job_ordering(qs, entity_type='shipment', sort='updated_desc')
        self.assertIn('updated_at', str(ordered.query.order_by))


class ShipmentJobCardTests(SimpleTestCase):
    def test_build_shipment_job_card_shape(self):
        shipment = MagicMock()
        shipment.shipment_id = uuid4()
        shipment.shipment_no = 'SH-001'
        shipment.shipment_status = 'In Transit'
        shipment.order_type = 'COD'
        shipment.pod_status = 'Pending'
        shipment.collection_status = 'Pending'
        shipment.cod_amount = 100
        shipment.route_display = 'A → B'
        shipment.updated_at = None
        shipment.created_at = None
        shipment.shipment_date = None
        shipment.booking = None
        shipment.truck = None
        shipment.loading_address = None
        shipment.delivery_address = None

        card = build_shipment_job_card(shipment, request=None)
        self.assertEqual(card['job_type'], 'shipment')
        self.assertEqual(card['shipment_no'], 'SH-001')
        self.assertIn('route_summary', card)
        self.assertIn('priority', card)
