"""
Allowed-actions DB prefilter tests (query shape, no database).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.allowed_actions_query import (
    _apply_mobile_scope_filter,
    _apply_movement_mobile_scope_filter,
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

    def test_movement_mobile_scope_includes_empty_move_category(self):
        qs = _apply_movement_mobile_scope_filter(TenantOperationAction.objects.all())
        sql = str(qs.query).lower()
        self.assertIn('empty_move', sql)
        self.assertIn('em', sql)

    def test_movement_mobile_scope_allows_empty_move_without_mobile_visible(self):
        qs = _apply_movement_mobile_scope_filter(TenantOperationAction.objects.all())
        sql = str(qs.query).lower()
        self.assertIn('mobile_visible', sql)
        self.assertIn('empty_move', sql)

    def test_movement_prefilter_keeps_empty_move_with_auto_shipment_post(self):
        from iroad_tenants.operation_runtime.allowed_actions_query import (
            _prefilter_movement_only_candidates,
        )
        from iroad_tenants.operation_runtime.movement_action_validator import (
            is_empty_movement,
        )
        from unittest.mock import MagicMock
        from uuid import uuid4

        movement = MagicMock()
        movement.pk = uuid4()
        movement.movement_source = 'empty'
        movement.empty_move_reason = 'Depot'
        self.assertTrue(is_empty_movement(movement))

        qs = _prefilter_movement_only_candidates(
            TenantOperationAction.objects.all(),
            movement=movement,
        )
        sql = str(qs.query).lower()
        self.assertIn('auto_shipment_post', sql)
        self.assertIn('empty_move', sql)

    @patch(
        'iroad_tenants.operation_runtime.allowed_actions_query.active_operation_actions_queryset',
    )
    @patch(
        'iroad_tenants.operation_runtime.allowed_actions_query.derive_shipment_execution_stage',
        return_value='pod',
    )
    def test_shipment_prefilter_keeps_label_only_pod_rows(self, _stage, mock_active):
        mock_active.return_value = TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
        )
        shipment = _shipment(TenantShipment.ShipmentStatus.LOADED)
        qs = prefilter_allowed_action_candidates(
            shipment=shipment,
            executed_action_ids=set(),
        )
        sql = str(qs.query).lower()
        self.assertIn('pod', sql)
        self.assertIn('proof of delivery', sql)

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

    @patch(
        'iroad_tenants.operation_runtime.allowed_actions_query.active_operation_actions_queryset',
    )
    @patch(
        'iroad_tenants.operation_runtime.allowed_actions_query.derive_shipment_execution_stage',
        return_value='cod',
    )
    def test_shipment_prefilter_keeps_payment_collection_at_pod_submitted(
        self,
        _stage,
        mock_active,
    ):
        mock_active.return_value = TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
        )
        shipment = _shipment(TenantShipment.ShipmentStatus.POD_SUBMITTED)
        shipment.order_type = 'COD'
        qs = prefilter_allowed_action_candidates(
            shipment=shipment,
            executed_action_ids=set(),
        )
        sql = str(qs.query).lower()
        self.assertIn('auto_treasury_post', sql)
        self.assertIn('payment collection', sql)
