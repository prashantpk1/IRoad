"""Tests for live dashboard resource stats payload."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from iroad_tenants.tenant_dashboard_overview import (
    _WorkspaceSnapshot,
    _build_quota_resource_bundle,
    _resource_row,
    build_tenant_resource_stats_payload,
)


class ResourceRowTests(SimpleTestCase):
    def test_resource_row_includes_key(self):
        row = _resource_row("users", "Internal Users", 3, 5, "indigo")
        self.assertEqual(row["key"], "users")
        self.assertEqual(row["current_display"], "3")
        self.assertEqual(row["total_display"], "5")
        self.assertEqual(row["pct_label"], "60%")

    def test_unlimited_cap(self):
        row = _resource_row("storage", "Storage GB", 0, -1, "amber")
        self.assertTrue(row["unlimited"])
        self.assertEqual(row["total_display"], "∞")
        self.assertEqual(row["pct_label"], "Unlimited")


class QuotaResourceBundleTests(SimpleTestCase):
    def test_bundle_shapes_rows_and_donut(self):
        profile = MagicMock()
        profile.active_max_users = 5
        profile.active_max_internal_trucks = 0
        profile.active_max_drivers = 0
        plan = MagicMock()
        plan.max_internal_users = 5
        plan.max_internal_trucks = 10
        plan.max_active_drivers = 10
        plan.max_monthly_shipments = 100
        plan.max_storage_gb = -1
        ws = _WorkspaceSnapshot(3, 2, 1, 40, 0)

        bundle = _build_quota_resource_bundle(profile, plan, ws)

        self.assertEqual(len(bundle["resource_rows"]), 5)
        self.assertEqual(bundle["resource_rows"][0]["key"], "users")
        self.assertIn("donut_style", bundle)
        self.assertEqual(len(bundle["donut_segments"]), 5)


class BuildTenantResourceStatsPayloadTests(SimpleTestCase):
    @patch("iroad_tenants.tenant_dashboard_overview._workspace_counts")
    @patch("iroad_tenants.tenant_dashboard_overview.TenantRegistry.objects.filter")
    @patch("iroad_tenants.tenant_dashboard_overview.TenantProfile.objects.select_related")
    def test_payload_includes_plan_and_usage(
        self,
        mock_select_related,
        mock_registry_filter,
        mock_workspace_counts,
    ):
        tenant = MagicMock()
        tenant.pk = "tenant-1"

        profile = MagicMock()
        profile.pk = "tenant-1"
        profile.current_plan = None
        profile.subscription_expiry_date = None
        profile.active_max_users = 0
        profile.active_max_internal_trucks = 0
        profile.active_max_drivers = 0

        mock_select_related.return_value.filter.return_value.first.return_value = profile

        registry = MagicMock()
        registry.schema_name = "tenant_schema"
        mock_registry_filter.return_value.first.return_value = registry

        mock_workspace_counts.return_value = _WorkspaceSnapshot(1, 1, 1, 5, 0)

        payload = build_tenant_resource_stats_payload(tenant)

        self.assertIn("plan_name", payload)
        self.assertIn("resource_rows", payload)
        self.assertIn("donut_segments", payload)
        self.assertIn("updated_at", payload)
        self.assertEqual(len(payload["resource_rows"]), 5)
