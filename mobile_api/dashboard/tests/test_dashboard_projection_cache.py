"""
Tests for per-request dashboard projection cache.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.services.dashboard_projection_cache import (
    DashboardProjectionCache,
    load_projection_cache,
)


class ProjectionCacheTests(SimpleTestCase):
    @patch(
        'mobile_api.dashboard.services.dashboard_projection_cache.scoped_shipment_action_logs',
    )
    def test_single_load_sets_latest_log_id(self, mock_scoped):
        log = MagicMock()
        log.log_id = 'log-99'
        mock_scoped.return_value = [log]

        shipment = MagicMock()
        shipment.pk = 1
        ctx = DriverDashboardContext(
            driver=MagicMock(pk=5, driver_id=5),
            tenant_schema='t',
            user_id='u',
            active_shipment=shipment,
        )
        cache = load_projection_cache(ctx)
        self.assertEqual(cache.latest_action_log_id, 'log-99')
        self.assertEqual(ctx.latest_action_log_id, 'log-99')
        self.assertEqual(cache.queries_executed, 1)

        cache2 = load_projection_cache(ctx)
        self.assertIs(cache2, cache)

    @patch(
        'mobile_api.dashboard.services.dashboard_projection_cache.scoped_preshipment_action_logs',
    )
    def test_booking_only_loads_preshipment_logs(self, mock_scoped):
        log = MagicMock()
        log.log_id = 'log-backload-1'
        mock_scoped.return_value = [log]

        booking = MagicMock()
        booking.pk = 10
        ctx = DriverDashboardContext(
            driver=MagicMock(pk=5, driver_id=5),
            tenant_schema='t',
            user_id='u',
            active_booking=booking,
        )
        cache = load_projection_cache(ctx)
        self.assertEqual(cache.latest_action_log_id, 'log-backload-1')
        self.assertEqual(len(cache.booking_logs), 1)
        mock_scoped.assert_called_once()

    def test_timeline_reuses_logs(self):
        logs = [MagicMock() for _ in range(7)]
        cache = DashboardProjectionCache(shipment_logs=logs)
        head = cache.timeline_logs(scope='shipment')
        self.assertEqual(len(head), 5)
