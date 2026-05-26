"""
Tests for dashboard polling cache, ETag, and content hash.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.services import dashboard_cache_service as cache_svc
from mobile_api.dashboard.services import dashboard_etag_service as etag_svc
from mobile_api.dashboard.services.dashboard_context_service import (
    DashboardContextService,
)
from mobile_api.dashboard.views.dashboard_view import DashboardAPIView
from rest_framework.test import APIRequestFactory, force_authenticate

from mobile_api.authentication import MobileUser


class EtagServiceTests(SimpleTestCase):
    def test_fingerprint_deterministic(self):
        ctx = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='tenant_a',
            user_id='u1',
        )
        fp1 = etag_svc.build_content_fingerprint(
            ctx,
            latest_action_log_id='log-1',
            pod_cod={'pod_pending': True, 'cod_pending': False},
        )
        fp2 = etag_svc.build_content_fingerprint(
            ctx,
            latest_action_log_id='log-1',
            pod_cod={'pod_pending': True, 'cod_pending': False},
        )
        self.assertEqual(
            etag_svc.fingerprint_digest(fp1),
            etag_svc.fingerprint_digest(fp2),
        )

    def test_workflow_change_changes_digest(self):
        ctx = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='t',
            user_id='u',
            workflow_projection={
                'allowed_actions': [{'action_code': 'A1'}],
                'current_stage': 'X',
                'next_action': {'action_code': 'A1'},
            },
        )
        fp1 = etag_svc.fingerprint_digest(
            etag_svc.build_content_fingerprint(ctx, latest_action_log_id='1')
        )
        ctx.workflow_projection = {
            'allowed_actions': [{'action_code': 'A2'}],
            'current_stage': 'X',
            'next_action': {'action_code': 'A2'},
        }
        fp2 = etag_svc.fingerprint_digest(
            etag_svc.build_content_fingerprint(ctx, latest_action_log_id='1')
        )
        self.assertNotEqual(fp1, fp2)

    def test_action_log_change_changes_invalidation_digest(self):
        ctx = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='t',
            user_id='u',
        )
        inv1 = etag_svc.fingerprint_digest(
            etag_svc.build_invalidation_fingerprint(ctx, latest_action_log_id='a')
        )
        inv2 = etag_svc.fingerprint_digest(
            etag_svc.build_invalidation_fingerprint(ctx, latest_action_log_id='b')
        )
        self.assertNotEqual(inv1, inv2)

    def test_movement_status_in_fingerprint(self):
        movement = types.SimpleNamespace(pk='m1', status='Scheduled')
        ctx = DriverDashboardContext(
            driver=MagicMock(),
            tenant_schema='t',
            user_id='u',
            active_empty_movement=movement,
        )
        d1 = etag_svc.fingerprint_digest(
            etag_svc.build_invalidation_fingerprint(ctx, latest_action_log_id='')
        )
        movement.status = 'In Progress'
        d2 = etag_svc.fingerprint_digest(
            etag_svc.build_invalidation_fingerprint(ctx, latest_action_log_id='')
        )
        self.assertNotEqual(d1, d2)

    def test_etag_matches_if_none_match(self):
        etag = '"abc123"'
        request = MagicMock()
        request.META = {'HTTP_IF_NONE_MATCH': etag}
        self.assertTrue(etag_svc.etag_matches_request(request, etag))


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    },
    MOBILE_DASHBOARD_CACHE_ENABLED=True,
)
class CacheServiceTests(SimpleTestCase):
    def test_cache_roundtrip(self):
        ctx = DriverDashboardContext(
            driver=MagicMock(pk=7),
            tenant_schema='tenant_x',
            user_id='u',
            workflow_projection={'allowed_actions': [], 'current_stage': ''},
            booking_projection={'booking_no': 'BK-1'},
            pod_cod_projection={'pod_pending': False},
        )
        inv = etag_svc.build_invalidation_fingerprint(ctx, latest_action_log_id='log-9')
        content = etag_svc.build_content_fingerprint(ctx, latest_action_log_id='log-9')
        etag = cache_svc.set_cached_projections(
            'tenant_x',
            7,
            inv,
            context=ctx,
            content_fingerprint=content,
        )
        loaded = cache_svc.get_cached_projections('tenant_x', 7, inv)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded['etag'], etag)
        self.assertEqual(loaded['booking_projection']['booking_no'], 'BK-1')


class Dashboard304Tests(SimpleTestCase):
    @patch('mobile_api.dashboard.views.dashboard_view.DashboardContextService')
    @patch('mobile_api.dashboard.views.dashboard_view.resolve_dashboard_driver')
    def test_view_returns_304_when_not_modified(self, mock_driver, mock_svc_cls):
        driver = MagicMock()
        driver.pk = driver.driver_id = uuid4()
        mock_driver.return_value = (driver, None, None)
        ctx = DriverDashboardContext(
            driver=driver,
            tenant_schema='t',
            user_id='u',
            poll_not_modified=True,
            dashboard_etag='"deadbeef"',
        )
        mock_svc_cls.return_value.resolve_driver_dashboard.return_value = (
            types.SimpleNamespace(
                context=ctx,
                etag='"deadbeef"',
                not_modified=True,
            )
        )

        from django.urls import reverse

        factory = APIRequestFactory()
        request = factory.get(
            reverse('mobile_api:driver_dashboard'),
            HTTP_IF_NONE_MATCH='"deadbeef"',
        )
        payload = {
            'user_id': str(uuid4()),
            'tenant_schema': 't',
            'driver_id': str(driver.driver_id),
        }
        force_authenticate(request, user=MobileUser(payload), token=payload)
        response = DashboardAPIView.as_view()(request)
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response['ETag'], '"deadbeef"')


class ContextPollingIntegrationTests(SimpleTestCase):
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.DashboardSummaryService',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.get_cached_projections',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.load_projection_cache',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.reconcile_dashboard_entities',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.DashboardMovementSelector',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.DashboardBookingSelector',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.assert_dashboard_scope_ownership',
    )
    def test_cache_hit_skips_full_projection_build(
        self,
        _mock_assert,
        mock_booking_cls,
        mock_movement_cls,
        mock_reconcile,
        _mock_load_cache,
        mock_cache_get,
        mock_summary_cls,
    ):
        def _recon(ctx, *, request=None, projection_cache=None):
            ctx.reconciliation = {
                'pod_cod_flags': {},
                'reconciliation_version': 'r',
                'compliance_projection_version': 'c',
                'workflow_integrity': {},
            }
            ctx.latest_action_log_id = 'log-100'

        mock_reconcile.side_effect = _recon
        mock_booking_cls.return_value.select_current_driver_booking.return_value = None
        mock_movement_cls.return_value.select_current_empty_move.return_value = None
        mock_summary_cls.return_value.build_summary.return_value = {
            'timeline_summary': {},
            'alerts': {'count': 0, 'items': []},
        }
        mock_summary_cls.return_value.build_sync_metadata.return_value = {}

        mock_cache_get.return_value = {
            'etag': '"cached-etag"',
            'booking_projection': {},
            'movement_projection': {},
            'workflow_projection': {'allowed_actions': [], 'current_stage': ''},
            'pod_cod_projection': {},
            'reconciliation': {'workflow_reconciled': True, 'any_drift': False},
        }

        driver = MagicMock()
        driver.pk = driver.driver_id = 5
        ctx = DashboardContextService().resolve_driver_dashboard_context(
            driver,
            tenant_schema='tenant_a',
            user_id='u1',
        )
        self.assertEqual(ctx.workflow_projection.get('current_stage'), '')
        mock_cache_get.assert_called_once()
