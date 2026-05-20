"""
Integration-style unit tests for driver dashboard hardening (no live tenant DB required).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.helpers.dashboard_cache import cache_key
from mobile_api.helpers.dashboard_ownership import DriverOwnershipScope
from mobile_api.helpers.dashboard_security import (
    sanitize_activity_items,
    sanitize_notification_items,
    sanitize_quick_actions,
)
from mobile_api.services.driver_dashboard_notifications import merge_summary_items


class DriverOwnershipScopeTests(SimpleTestCase):
    def test_owns_shipment_and_movement_o1(self):
        scope = DriverOwnershipScope(
            shipment_ids=frozenset({'11111111-1111-4111-8111-111111111111'}),
            movement_ids=frozenset({'22222222-2222-4222-8222-222222222222'}),
        )
        self.assertTrue(
            scope.owns_shipment('11111111-1111-4111-8111-111111111111')
        )
        self.assertFalse(
            scope.owns_shipment('99999999-9999-4999-8999-999999999999')
        )
        self.assertTrue(
            scope.owns_movement('22222222-2222-4222-8222-222222222222')
        )


class DashboardSanitizeTests(SimpleTestCase):
    def test_sanitize_activity_drops_foreign_ids_without_db(self):
        scope = DriverOwnershipScope(
            shipment_ids=frozenset({'11111111-1111-4111-8111-111111111111'}),
            movement_ids=frozenset(),
        )
        items = [
            {'shipment_id': '11111111-1111-4111-8111-111111111111'},
            {'shipment_id': '99999999-9999-4999-8999-999999999999'},
        ]
        out = sanitize_activity_items(items=items, scope=scope)
        self.assertEqual(len(out), 1)

    def test_sanitize_notifications_no_exists_calls(self):
        scope = DriverOwnershipScope(shipment_ids=frozenset(), movement_ids=frozenset())
        items = [{'shipment_id': '11111111-1111-4111-8111-111111111111'}]
        with patch(
            'mobile_api.helpers.dashboard_security.shipment_queryset_for_driver'
        ) as mock_qs:
            sanitize_notification_items(items=items, scope=scope)
        mock_qs.assert_not_called()

    def test_sanitize_quick_actions_strips_unknown_ids(self):
        scope = DriverOwnershipScope(
            shipment_ids=frozenset({'11111111-1111-4111-8111-111111111111'}),
            movement_ids=frozenset(),
        )
        actions = [{'id': 'a', 'shipment_id': '99999999-9999-4999-8999-999999999999'}]
        out = sanitize_quick_actions(actions=actions, scope=scope)
        self.assertNotIn('shipment_id', out[0])


class NotificationSummaryTests(SimpleTestCase):
    def test_merge_dedupes_by_id(self):
        persisted = [{'id': 'x', 'created_at': '2026-01-02T00:00:00Z'}]
        push_rows = [{'id': 'x', 'created_at': '2026-01-01T00:00:00Z'}]
        ephemeral = [{'id': 'y', 'created_at': '2026-01-03T00:00:00Z'}]
        merged = merge_summary_items(
            persisted=persisted,
            push_rows=push_rows,
            ephemeral=ephemeral,
            limit=10,
        )
        ids = [r['id'] for r in merged]
        self.assertEqual(len(ids), len(set(ids)))

    def test_unread_count_uses_inbox_only(self):
        from mobile_api.services.driver_dashboard_notifications import (
            build_notifications_summary,
        )

        driver = SimpleNamespace(driver_id='d1', pk=1)
        with patch(
            'mobile_api.services.driver_dashboard_notifications.aggregate_inbox_counts',
            return_value={
                'unread_count': 3,
                'critical_count': 0,
                'assignment_count': 0,
                'operational_warnings_count': 1,
            },
        ), patch(
            'mobile_api.services.driver_dashboard_notifications.build_ephemeral_operational_warnings',
            return_value=[
                {
                    'id': 'eph:1',
                    'category': 'operational_warning',
                    'is_read': False,
                }
            ],
        ), patch(
            'mobile_api.services.driver_dashboard_notifications.fetch_push_receipt_projections',
            return_value=[{'id': 'push:1'}],
        ), patch(
            'mobile_api.services.driver_dashboard_notifications.fetch_inbox_item_projections',
            return_value=[],
        ), patch(
            'mobile_api.services.driver_dashboard_notifications.build_fcm_context',
            return_value={'push_enabled': False},
        ):
            summary = build_notifications_summary(
                driver=driver,
                tenant_schema='tenant_a',
            )
        self.assertEqual(summary['unread_count'], 3)
        self.assertEqual(summary['push_recent_count'], 1)
        self.assertEqual(summary['ephemeral_hint_count'], 1)


class DashboardCacheTests(SimpleTestCase):
    def test_cache_key_includes_tenant_and_driver(self):
        key = cache_key(
            tenant_schema='acme',
            driver_id='drv-1',
            slice_name='current_job',
        )
        self.assertIn('acme', key)
        self.assertIn('drv-1', key)
        self.assertIn('current_job', key)


class SecureContextTests(SimpleTestCase):
    def test_tenant_mismatch_rejected(self):
        from mobile_api.helpers.dashboard_security import resolve_secure_dashboard_context

        with patch(
            'mobile_api.services.driver_profile_service._resolve_driver_context',
            return_value={'success': True, 'driver': MagicMock(driver_id='d'), 'tenant_user': MagicMock()},
        ):
            result = resolve_secure_dashboard_context(
                user_id='u1',
                tenant_schema='tenant_a',
                jwt_payload={'tenant_schema': 'tenant_b'},
            )
        self.assertFalse(result['success'])
