"""
Tests for ``dashboard_status_reconciler`` (read-only reconciliation + overlays).
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.services import dashboard_status_reconciler as dsr


class ReconcilerSliceTests(SimpleTestCase):
    def test_matching_log_and_column_no_drift(self):
        raw = {
            'authoritative_status': 'In Transit',
            'column_status': 'In Transit',
            'drift': {'has_drift': False, 'reason': None},
            'timeline': {'log_count': 3},
        }
        s = dsr._slice_reconciled_state(raw)
        self.assertEqual(s['authoritative_status'], 'In Transit')
        self.assertEqual(s['status_source'], 'action_logs')
        self.assertFalse(s['drift_detected'])

    def test_drifted_shipment_status(self):
        raw = {
            'authoritative_status': 'Loaded',
            'column_status': 'In Transit',
            'drift': {
                'has_drift': True,
                'reason': 'column_ahead_of_action_logs',
            },
            'timeline': {'log_count': 2},
        }
        s = dsr._slice_reconciled_state(raw)
        self.assertTrue(s['drift_detected'])
        self.assertIn('column_ahead', s['drift_reason'])

    def test_missing_logs_uses_column(self):
        raw = {
            'authoritative_status': '',
            'column_status': 'Loaded',
            'drift': {'has_drift': False},
            'timeline': {'log_count': 0},
        }
        s = dsr._slice_reconciled_state(raw)
        self.assertEqual(s['authoritative_status'], 'Loaded')
        self.assertEqual(s['status_source'], 'columns_fallback')


class OverlayTests(SimpleTestCase):
    def test_overlay_restores_shipment_status(self):
        shipment = MagicMock()
        shipment.shipment_status = 'Loaded'
        ctx = DriverDashboardContext(
            driver=MagicMock(pk=1),
            tenant_schema='t',
            user_id='u',
            active_shipment=shipment,
        )
        ctx.reconciliation = {
            'shipment': {
                'authoritative_status': 'In Transit',
                'workflow_integrity': {
                    'authority_source': 'action_logs',
                    'log_count': 1,
                    'fallback_to_columns': False,
                    'missing_log_warning': False,
                },
                'raw': {
                    'authoritative_status': 'In Transit',
                    'timeline': {'log_count': 1},
                },
            }
        }
        with dsr.apply_reconciled_status_overlays(ctx):
            self.assertEqual(shipment.shipment_status, 'In Transit')
        self.assertEqual(shipment.shipment_status, 'Loaded')

    def test_fallback_overlay_with_missing_log_warning(self):
        shipment = MagicMock()
        shipment.shipment_status = 'Loaded'
        ctx = DriverDashboardContext(
            driver=MagicMock(pk=1),
            tenant_schema='t',
            user_id='u',
            active_shipment=shipment,
        )
        ctx.reconciliation = {
            'shipment': {
                'authoritative_status': 'Loaded',
                'raw': {
                    'authoritative_status': 'Loaded',
                    'column_status': 'Loaded',
                    'timeline': {'log_count': 0},
                    'drift': {'has_drift': False},
                },
                'workflow_integrity': {
                    'authority_source': 'columns_fallback',
                    'missing_log_warning': True,
                    'fallback_to_columns': True,
                    'log_count': 0,
                },
            }
        }
        with dsr.apply_reconciled_status_overlays(ctx):
            self.assertEqual(shipment.shipment_status, 'Loaded')
        self.assertEqual(shipment.shipment_status, 'Loaded')

    def test_workflow_integrity_missing_logs(self):
        wi = dsr.build_workflow_integrity(
            log_count=0,
            authoritative_status='Loaded',
            column_status='Loaded',
            drift_detected=False,
            status_source='column',
        )
        self.assertTrue(wi['missing_log_warning'])
        self.assertTrue(wi['fallback_to_columns'])
        self.assertEqual(wi['workflow_integrity_state'], dsr.INTEGRITY_MISSING_LOGS)


class ReconcileDashboardEntitiesTests(SimpleTestCase):
    @patch.object(
        dsr,
        'reconcile_shipment_execution_state',
        return_value={
            'authoritative_status': 'Loaded',
            'column_status': 'In Transit',
            'drift': {'has_drift': True, 'reason': 'column_ahead_of_action_logs'},
            'timeline': {'log_count': 1},
        },
    )
    def test_reconcile_sets_context_bundle(self, _mock_ship):
        driver = MagicMock()
        driver.pk = driver.driver_id = 9
        shipment = MagicMock()
        shipment.shipment_status = 'In Transit'
        ctx = DriverDashboardContext(
            driver=driver,
            tenant_schema='t1',
            user_id='u1',
            active_shipment=shipment,
        )
        dsr.reconcile_dashboard_entities(ctx, request=None)
        self.assertTrue(ctx.reconciliation.get('workflow_reconciled'))
        self.assertTrue(ctx.reconciliation.get('any_drift'))
        self.assertTrue((ctx.reconciliation.get('shipment') or {}).get('drift_detected'))

    @patch.object(
        dsr,
        'reconcile_movement_execution_state',
        return_value={
            'authoritative_status': 'In Progress',
            'movement_status': 'Scheduled',
            'drift': {'has_drift': True, 'reason': 'movement_column_behind_logs'},
            'timeline': {'log_count': 2},
        },
    )
    def test_movement_drift_surfaces(self, _mock_mov):
        driver = MagicMock()
        driver.pk = driver.driver_id = 3
        movement = MagicMock()
        movement.status = 'Scheduled'
        ctx = DriverDashboardContext(
            driver=driver,
            tenant_schema='t1',
            user_id='u1',
            active_empty_movement=movement,
        )
        dsr.reconcile_dashboard_entities(ctx, request=None)
        self.assertTrue((ctx.reconciliation.get('movement') or {}).get('drift_detected'))


class StripRawBundleTests(SimpleTestCase):
    def test_strip_raw_removes_payload(self):
        bundle = {
            'workflow_reconciled': True,
            'any_drift': True,
            'shipment': {
                'authoritative_status': 'X',
                'status_source': 'action_logs',
                'drift_detected': True,
                'drift_reason': 'r',
                'raw': {'secret': 1},
            },
        }
        out = dsr.strip_raw_reconciliation_bundle(bundle)
        self.assertNotIn('raw', out.get('shipment') or {})


class ReconciledAllowedActionsTests(SimpleTestCase):
    @patch(
        'mobile_api.dashboard.projections.workflow_projection.derive_job_execution_stage',
        return_value={'entity_type': 'shipment'},
    )
    @patch(
        'mobile_api.dashboard.projections.workflow_projection.OperationExecutionService.get_allowed_driver_actions',
        return_value={'actions': [], 'primary_action': {}, 'count': 0},
    )
    def test_engine_sees_overlaid_shipment_status(self, mock_allowed, _mock_stage):
        from mobile_api.dashboard.projections.workflow_projection import (
            build_shipment_workflow,
        )

        seen_status: list[str] = []

        def _capture(**kwargs):
            seen_status.append(kwargs['shipment'].shipment_status)
            return {'actions': [], 'primary_action': {}, 'count': 0}

        mock_allowed.side_effect = _capture

        shipment = types.SimpleNamespace(
            pk='s1',
            shipment_id='s1',
            shipment_no='SH-1',
            booking_item_type='Outbound',
            shipment_status='Loaded',
        )
        booking = types.SimpleNamespace()
        ctx = DriverDashboardContext(
            driver=MagicMock(pk=1),
            tenant_schema='t',
            user_id='u',
            active_shipment=shipment,
            active_booking=booking,
        )
        ctx.reconciliation = {
            'shipment': {
                'authoritative_status': 'In Transit',
                'workflow_integrity': {
                    'authority_source': 'action_logs',
                    'log_count': 1,
                    'fallback_to_columns': False,
                    'missing_log_warning': False,
                },
                'raw': {
                    'authoritative_status': 'In Transit',
                    'timeline': {'log_count': 1},
                },
            }
        }
        with dsr.apply_reconciled_status_overlays(ctx):
            build_shipment_workflow(shipment, booking=booking, request=None)
        self.assertEqual(seen_status, ['In Transit'])
        self.assertEqual(shipment.shipment_status, 'Loaded')
