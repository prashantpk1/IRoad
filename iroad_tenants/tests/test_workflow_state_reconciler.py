"""
Workflow state reconciliation tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.latest_action_aggregator import (
    derive_shipment_status_from_logs,
    shipment_status_rank,
)
from iroad_tenants.operation_runtime.workflow_state_reconciler import (
    _build_drift,
)


class DriftDetectionTests(SimpleTestCase):
    def test_detects_column_behind_logs(self):
        drift = _build_drift(
            column_status='Loaded',
            authoritative_status='In Transit',
            latest_impact_status='In Transit',
            peak_impact_status='In Transit',
            execution_sub_stage='in_transit',
        )
        self.assertTrue(drift['has_drift'])
        self.assertEqual(drift['reason'], 'column_behind_action_logs')

    def test_in_sync_when_column_matches(self):
        drift = _build_drift(
            column_status='In Transit',
            authoritative_status='In Transit',
            latest_impact_status='In Transit',
            peak_impact_status='In Transit',
            execution_sub_stage='in_transit',
        )
        self.assertFalse(drift['has_drift'])


class LogAggregationTests(SimpleTestCase):
    def test_peak_rank_picks_furthest_progress(self):
        log_a = MagicMock()
        log_a.operation_action = MagicMock()
        log_a.operation_action.shipment_status_impact = 'Loaded'
        log_a.operation_action.movement_status_impact = ''
        log_a.operation_action.action_code = 'A4'

        log_b = MagicMock()
        log_b.operation_action = MagicMock()
        log_b.operation_action.shipment_status_impact = 'In Transit'
        log_b.operation_action.movement_status_impact = ''
        log_b.operation_action.action_code = 'A5'

        with patch(
            'iroad_tenants.operation_runtime.latest_action_aggregator._is_reversal_action',
            return_value=False,
        ):
            evidence = derive_shipment_status_from_logs([log_b, log_a])

        self.assertEqual(evidence['authoritative_status'], 'In Transit')
        self.assertGreater(
            shipment_status_rank('In Transit'),
            shipment_status_rank('Loaded'),
        )
