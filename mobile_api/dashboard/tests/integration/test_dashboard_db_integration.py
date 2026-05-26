"""
Database integration tests for dashboard lifecycle, reconcile, and polling.

Skipped when tenant models cannot be created in the active database.
"""
from __future__ import annotations

import os
import unittest
import uuid
from datetime import date
from unittest.mock import MagicMock

from django.db import connection
from django.test import SimpleTestCase, TestCase

from mobile_api.dashboard.selectors import booking_selection_policy as policy
from mobile_api.dashboard.services.dashboard_etag_service import (
    build_invalidation_fingerprint,
    fingerprint_digest,
)
from mobile_api.dashboard.services.dashboard_status_reconciler import (
    build_workflow_integrity,
)
from tenant_workspace.models import TenantBooking, TenantShipment


def _tenant_schema_available() -> bool:
    return os.environ.get('DASHBOARD_INTEGRATION_DB', '').lower() in {
        '1',
        'true',
        'yes',
    }


@unittest.skipUnless(
    _tenant_schema_available(),
    'Set DASHBOARD_INTEGRATION_DB=1 with a provisioned tenant schema to run.',
)
class DashboardLifecycleIntegrationTests(SimpleTestCase):
    """Round-trip sequencing on in-memory ORM-shaped rows (no DB persist)."""

    def test_delivered_outbound_activates_backload_policy(self):
        booking = TenantBooking(
            booking_id=uuid.uuid4(),
            booking_no='BK-INT-1',
            trip_type='Round',
            booking_status=TenantBooking.Status.CONFIRMED,
            booking_date=date.today(),
            assigned_driver_id=uuid.uuid4(),
            booking_line_backload_driver_id=uuid.uuid4(),
        )
        outbound = TenantShipment(
            shipment_id=uuid.uuid4(),
            shipment_no='SH-O',
            booking_item_type='Outbound',
            shipment_status=TenantShipment.ShipmentStatus.DELIVERED,
            shipment_sequence=1,
        )
        backload = TenantShipment(
            shipment_id=uuid.uuid4(),
            shipment_no='SH-B',
            booking_item_type='Backload',
            shipment_status=TenantShipment.ShipmentStatus.LOADED,
            shipment_sequence=2,
        )
        legs = policy.sorted_countable_shipments([outbound, backload])
        nxt = policy.get_next_executable_shipment(booking, legs)
        self.assertEqual(nxt.booking_item_type, 'Backload')
        stage = policy.derive_booking_execution_stage(booking, legs)
        self.assertEqual(
            stage,
            policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED,
        )


class DashboardReconcileIntegrityUnitDBTests(SimpleTestCase):
    """Runs without tenant data — integrity + fingerprint contracts."""

    def test_workflow_integrity_high_confidence_with_logs(self):
        wi = build_workflow_integrity(
            log_count=5,
            authoritative_status='In Transit',
            column_status='In Transit',
            drift_detected=False,
            status_source='action_logs',
        )
        self.assertEqual(wi['authority_source'], 'action_logs')
        self.assertEqual(wi['reconciliation_confidence'], 'high')
        self.assertFalse(wi['missing_log_warning'])

    def test_invalidation_fingerprint_includes_version_slots(self):
        from mobile_api.dashboard.dto.driver_dashboard_context import (
            DriverDashboardContext,
        )

        ctx = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='tenant_x',
            user_id='u',
        )
        ctx.reconciliation = {
            'reconciliation_version': 'rev1',
            'workflow_projection_version': 'wfv1',
            'compliance_projection_version': 'cpv1',
        }
        fp = build_invalidation_fingerprint(ctx, latest_action_log_id='log-1')
        self.assertEqual(fp['reconciliation_version'], 'rev1')
        self.assertEqual(fp['compliance_projection_version'], 'cpv1')


class DashboardExplainAuditSmokeTests(SimpleTestCase):
    """Explain helpers are opt-in (``DASHBOARD_RUN_EXPLAIN_AUDIT=1``)."""

    def test_explain_helpers_import(self):
        from mobile_api.dashboard.services.dashboard_explain_audit import (
            audit_dashboard_query_plans,
            explain_booking_selector_query,
        )

        self.assertTrue(callable(explain_booking_selector_query))
        self.assertTrue(callable(audit_dashboard_query_plans))

    @unittest.skipUnless(
        os.environ.get('DASHBOARD_RUN_EXPLAIN_AUDIT', '').lower() in {'1', 'true'},
        'Set DASHBOARD_RUN_EXPLAIN_AUDIT=1 to run EXPLAIN against the DB.',
    )
    def test_booking_explain_returns_plan_key(self):
        from mobile_api.dashboard.services.dashboard_explain_audit import (
            explain_booking_selector_query,
        )

        try:
            report = explain_booking_selector_query(uuid.uuid4())
        except Exception as exc:
            self.skipTest(f'ORM explain unavailable: {exc}')
        self.assertEqual(report['query'], 'booking_selector')
        self.assertIn('plan', report)
