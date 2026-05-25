"""
Allowed-actions DB prefilter tests (query shape, no database).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.allowed_actions_query import (
    _apply_mobile_scope_filter,
    prefilter_allowed_action_candidates,
)
from tenant_workspace.models import TenantOperationAction, TenantShipment


def _shipment(status=TenantShipment.ShipmentStatus.LOADED):
    s = MagicMock()
    s.pk = uuid4()
    s.shipment_status = status
    s.order_type = 'Standard'
    s.collection_status = ''
    return s


class AllowedActionsPrefilterTests(SimpleTestCase):
    def test_mobile_scope_filter_sql(self):
        qs = _apply_mobile_scope_filter(TenantOperationAction.objects.all())
        sql = str(qs.query).lower()
        self.assertIn('action_scope', sql)

    @patch(
        'iroad_tenants.operation_runtime.allowed_actions_query.active_operation_actions_queryset',
    )
    @patch(
        'iroad_tenants.operation_runtime.allowed_actions_query.derive_shipment_execution_stage',
        return_value='pickup',
    )
    def test_shipment_prefilter_sql_mentions_stage_fields(self, _stage, mock_active):
        mock_active.return_value = TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
        )
        shipment = _shipment(TenantShipment.ShipmentStatus.LOADED)
        qs = prefilter_allowed_action_candidates(
            shipment=shipment,
            executed_action_ids=set(),
        )
        sql = str(qs.query).lower()
        self.assertIn('auto_shipment_post', sql)
        self.assertIn('shipment_status_impact', sql)
        self.assertIn('action_scope', sql)
