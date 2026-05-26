"""
Tests for POD/COD compliance reconciliation.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.services.dashboard_pod_cod_reconciler import (
    reconcile_pod_cod_compliance,
)
from tenant_workspace.models import TenantShipment


def _action(code: str, label: str = ''):
    a = MagicMock()
    a.action_code = code
    a.english_label = label or code
    a.shipment_status_impact = ''
    a.movement_status_impact = ''
    return a


def _log(action):
    row = MagicMock()
    row.operation_action = action
    return row


class PodCodReconcilerTests(SimpleTestCase):
    def test_compliance_drift_cod_without_log(self):
        shipment = MagicMock()
        shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
        shipment.pod_status = TenantShipment.PodStatus.COMPLIANT
        shipment.order_type = 'COD'
        shipment.collection_status = TenantShipment.CollectionStatus.COLLECTED

        ctx = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='t',
            user_id='u',
            active_shipment=shipment,
        )
        from mobile_api.dashboard.services.dashboard_projection_cache import (
            DashboardProjectionCache,
        )

        ctx.projection_cache = DashboardProjectionCache(shipment_logs=[])

        with patch(
            'mobile_api.dashboard.selectors.pod_cod_policy.derive_treasury_pending',
            return_value=False,
        ):
            result = reconcile_pod_cod_compliance(ctx)
            integrity = result['compliance_integrity']
            self.assertTrue(integrity['compliance_drift'])
            self.assertIn(
                'cod_collected_column_without_collection_log',
                integrity['drift_reasons'],
            )

    def test_pod_upload_log_vs_pending_column(self):
        shipment = MagicMock()
        shipment.shipment_status = TenantShipment.ShipmentStatus.AT_DELIVERY
        shipment.pod_status = TenantShipment.PodStatus.PENDING
        shipment.order_type = 'Prepaid'
        shipment.collection_status = ''

        ctx = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='t',
            user_id='u',
            active_shipment=shipment,
        )
        from mobile_api.dashboard.services.dashboard_projection_cache import (
            DashboardProjectionCache,
        )

        ctx.projection_cache = DashboardProjectionCache(
            shipment_logs=[_log(_action('A8', 'Upload POD'))],
        )

        result = reconcile_pod_cod_compliance(ctx)
        self.assertTrue(result['compliance_integrity']['compliance_drift'])
        self.assertEqual(
            result['compliance_integrity']['authority_source'],
            'action_logs',
        )
