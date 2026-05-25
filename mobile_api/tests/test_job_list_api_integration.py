"""
API integration tests for driver job list (mocked auth/context; no live tenant DB).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.permissions import AllowAny
from rest_framework.test import force_authenticate

from mobile_api.helpers.job_list_cursor import (
    encode_cursor_from_row,
    parse_cursor_param,
    resolve_pagination_mode,
)
from mobile_api.helpers.job_list_driver_scope import job_list_union_driver_scope_enabled
from mobile_api.helpers.job_list_guards import enforce_payload_limit, reject_all_tab_without_queue
from mobile_api.helpers.job_list_performance import resolve_include_total
from mobile_api.permissions import HasDriverJobsAccess
from rest_framework.response import Response
from mobile_api.views.driver_jobs import DriverJobSummaryView
from mobile_api.views.driver_shipment_jobs import DriverShipmentJobListActiveView


class JobListApiIntegrationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.driver_id = uuid4()
        self.user = SimpleNamespace(
            is_authenticated=True,
            pk=self.driver_id,
            driver_id=self.driver_id,
        )
        self.ctx = SimpleNamespace(
            driver=SimpleNamespace(pk=self.driver_id, driver_id=self.driver_id),
            tenant_schema='tenant_test',
            driver_id=str(self.driver_id),
            user_id='user-1',
            tenant_user=SimpleNamespace(),
            ownership_scope=None,
        )

    def _jwt_patch(self):
        return patch.multiple(
            'mobile_api.views.driver_jobs',
            _mobile_user_id=MagicMock(return_value='user-1'),
            _mobile_tenant_schema=MagicMock(return_value='tenant_test'),
            _mobile_jwt_payload=MagicMock(
                return_value={
                    'tenant_schema': 'tenant_test',
                    'driver_id': str(self.driver_id),
                    'role_name': 'driver',
                }
            ),
        )

    @override_settings(MOBILE_JOB_LIST_INCLUDE_TOTAL_DEFAULT=False)
    def test_include_total_default_false(self):
        request = self.factory.get('/api/v1/mobile/driver/jobs/shipments/active/')
        request.query_params = request.GET
        self.assertFalse(resolve_include_total(request))

    @override_settings(MOBILE_JOB_LIST_INCLUDE_TOTAL_DEFAULT=False)
    def test_include_total_opt_in(self):
        request = self.factory.get('/', {'include_total': '1'})
        request.query_params = request.GET
        self.assertTrue(resolve_include_total(request))

    @override_settings(MOBILE_API_JOBS_DISALLOW_TAB_ALL=True)
    def test_tab_all_rejected(self):
        err = reject_all_tab_without_queue('all', entity_type='shipment')
        self.assertIsNotNone(err)

    @override_settings(MOBILE_API_JOBS_DEFAULT_PAGINATION='cursor')
    def test_default_pagination_cursor(self):
        request = self.factory.get('/api/v1/mobile/driver/jobs/shipments/active/')
        request.query_params = request.GET
        self.assertEqual(resolve_pagination_mode(request), 'cursor')

    @override_settings(MOBILE_API_JOBS_ALLOW_OFFSET_PAGINATION=True)
    def test_page_param_forces_offset_when_legacy_enabled(self):
        request = self.factory.get('/', {'page': '2'})
        request.query_params = request.GET
        self.assertEqual(resolve_pagination_mode(request), 'offset')

    @override_settings(MOBILE_API_JOBS_ALLOW_OFFSET_PAGINATION=False)
    def test_page_param_ignored_when_offset_disabled(self):
        request = self.factory.get('/', {'page': '2'})
        request.query_params = request.GET
        self.assertEqual(resolve_pagination_mode(request), 'cursor')

    @override_settings(
        MOBILE_API_JOBS_STRICT_PAYLOAD=False,
        MOBILE_API_JOBS_ENFORCE_PAYLOAD_LIMIT=True,
        MOBILE_API_JOBS_MAX_RESPONSE_BYTES=200,
    )
    def test_payload_enforcement_truncates_when_not_strict(self):
        big = [{'id': str(i)} for i in range(80)]
        out, err, code = enforce_payload_limit(big)
        self.assertIsNotNone(out)
        self.assertLess(len(out), len(big))
        self.assertEqual(code, 'job_list_payload_truncated')

    @override_settings(MOBILE_API_JOBS_STRICT_PAYLOAD=True, MOBILE_API_JOBS_MAX_RESPONSE_BYTES=50)
    def test_strict_payload_rejects(self):
        out, err, code = enforce_payload_limit([{'x': 'y' * 200}])
        self.assertIsNone(out)
        self.assertEqual(code, 'job_list_payload_too_large')

    @override_settings(MOBILE_API_JOBS_ALLOW_OFFSET_PAGINATION=False)
    def test_offset_rejected_by_default(self):
        from mobile_api.helpers.job_list_guards import reject_offset_pagination

        request = self.factory.get('/', {'page': '2'})
        request.query_params = request.GET
        self.assertIsNotNone(reject_offset_pagination(request))

    def test_has_driver_jobs_access_requires_driver(self):
        request = self.factory.get('/')
        request.user = SimpleNamespace(is_authenticated=True)
        with patch(
            'mobile_api.permissions.user_in_driver_group',
            return_value=False,
        ):
            self.assertFalse(HasDriverJobsAccess().has_permission(request, MagicMock()))

    @patch.object(DriverJobSummaryView, 'authentication_classes', [])
    @patch.object(DriverJobSummaryView, 'permission_classes', [AllowAny])
    @patch('mobile_api.views.driver_jobs.resolve_secure_job_list_context')
    @patch('mobile_api.views.driver_jobs.build_job_summary')
    @patch('mobile_api.views.driver_jobs.get_cached_job_summary', return_value=None)
    def test_summary_view_success(self, _cache, mock_summary, mock_ctx):
        mock_ctx.return_value = {'success': True, 'ctx': self.ctx}
        mock_summary.return_value = {
            'counters': {
                'active_shipments': 1,
                'completed_shipments': 0,
                'cancelled_shipments': 0,
                'active_movements': 0,
                'completed_movements': 0,
                'cancelled_movements': 0,
                'pod_pending': 0,
                'cod_pending': 0,
            },
            'entity_types': ('shipment', 'movement'),
        }
        request = self.factory.get('/api/v1/mobile/driver/jobs/summary/')
        with self._jwt_patch():
            response = DriverJobSummaryView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get('status'), 1)

    @patch.object(DriverShipmentJobListActiveView, 'authentication_classes', [])
    @patch.object(DriverShipmentJobListActiveView, 'permission_classes', [AllowAny])
    @patch('mobile_api.views.driver_jobs.resolve_secure_job_list_context')
    @patch('mobile_api.views.driver_jobs.hydrate_job_list_page_actions')
    @patch('mobile_api.views.driver_jobs.sanitize_job_list_page', side_effect=lambda rows, **k: rows)
    def test_shipment_active_list_cursor_response_shape(
        self,
        _san,
        _hydrate,
        mock_ctx,
    ):
        mock_ctx.return_value = {'success': True, 'ctx': self.ctx}
        shipment = SimpleNamespace(
            shipment_id=uuid4(),
            shipment_no='SH-1',
            updated_at=None,
            created_at=None,
            pk=uuid4(),
        )
        qs = MagicMock()
        qs.__getitem__ = MagicMock(return_value=[shipment])
        qs.filter.return_value = qs
        qs.order_by.return_value = qs

        with patch(
            'mobile_api.services.driver_shipment_list_service.list_driver_shipments',
        ) as mock_list:
            mock_list.return_value = {
                'success': True,
                'queryset': qs,
                'include_actions': False,
                'meta': {
                    'entity_type': 'shipment',
                    'tab': 'active',
                    'queue': 'none',
                    'sort': 'updated_desc',
                },
            }
            card = {
                'job_id': str(shipment.shipment_id),
                'job_type': 'shipment',
                'job_no': 'SH-1',
                'current_status': '',
                'needs_pod': False,
                'needs_cod': False,
                'is_active': False,
                'is_empty_move': False,
            }
            with patch(
                'mobile_api.views.driver_shipment_jobs.build_shipment_job_card',
                return_value=card,
            ):
                request = self.factory.get(
                    '/api/v1/mobile/driver/jobs/shipments/active/',
                    {'page_size': '1'},
                )
                request.query_params = request.GET
                mock_paginator = MagicMock()
                mock_paginator.paginate_queryset.return_value = [shipment]
                mock_paginator.pagination_error = None
                mock_paginator.pagination_mode = 'cursor'
                mock_paginator.next_cursor = 'tok'
                mock_paginator.has_more = False
                mock_paginator.get_page_size.return_value = 1
                mock_paginator.get_paginated_response.return_value = Response(
                    {
                        'status': 1,
                        'message': 'ok',
                        'data': {
                            'items': [],
                            'pagination_mode': 'cursor',
                            'has_more': False,
                            'next_cursor': 'tok',
                            'page_size': 1,
                        },
                    }
                )
                with self._jwt_patch(), patch(
                    'mobile_api.views.driver_jobs.MobileJobListPagination',
                    return_value=mock_paginator,
                ):
                    response = DriverShipmentJobListActiveView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        data = response.data.get('data') or {}
        self.assertIn('pagination_mode', data)
        self.assertIn('items', data)

    @override_settings(MOBILE_API_JOBS_UNION_DRIVER_SCOPE=True)
    def test_union_scope_enabled(self):
        self.assertTrue(job_list_union_driver_scope_enabled())

    def test_cursor_roundtrip(self):
        row = SimpleNamespace(
            shipment_id=uuid4(),
            updated_at=None,
            created_at=None,
        )
        token = encode_cursor_from_row(row, entity_type='shipment', sort='updated_desc')
        self.assertIsNotNone(token)
        request = self.factory.get('/', {'cursor': token})
        request.query_params = request.GET
        parsed = parse_cursor_param(request, entity_type='shipment')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.sort, 'updated_desc')
