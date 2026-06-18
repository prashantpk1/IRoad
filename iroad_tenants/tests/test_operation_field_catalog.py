"""Operational POD field catalog tests."""
from __future__ import annotations

from django.test import SimpleTestCase

from iroad_tenants.operation_field_catalog import (
    normalize_operation_pod_status,
    normalize_operation_pod_type,
    operation_pod_status_options,
    operation_pod_type_options,
)
from tenant_workspace.models import TenantShipment


class OperationPodFieldCatalogTests(SimpleTestCase):
    def test_pod_type_options_match_spec(self):
        self.assertEqual(
            operation_pod_type_options(),
            ('Digital', 'Soft Copy', 'Hard Copy'),
        )

    def test_pod_status_options_match_spec(self):
        self.assertEqual(
            operation_pod_status_options(),
            ('Completed', 'Not Completed'),
        )

    def test_normalize_legacy_pod_type_values(self):
        self.assertEqual(normalize_operation_pod_type('Soft'), TenantShipment.PodType.SOFT)
        self.assertEqual(normalize_operation_pod_type('Hard'), TenantShipment.PodType.HARD)
        self.assertEqual(
            normalize_operation_pod_type('Soft Copy'),
            TenantShipment.PodType.SOFT,
        )

    def test_normalize_legacy_pod_status_values(self):
        self.assertEqual(
            normalize_operation_pod_status('Compliant'),
            TenantShipment.PodStatus.COMPLETED,
        )
        self.assertEqual(
            normalize_operation_pod_status('Pending'),
            TenantShipment.PodStatus.NOT_COMPLETED,
        )
        self.assertEqual(
            normalize_operation_pod_status('Hard Copy Received'),
            TenantShipment.PodStatus.NOT_COMPLETED,
        )
