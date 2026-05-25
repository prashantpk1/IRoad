"""
Job Detail module — real JWT, DRF authentication, tenant binding, and ownership E2E.

Requires PostgreSQL with a Job Detail READY tenant schema on the dev database:

  $env:MOBILE_API_JOB_DETAIL_TEST_USE_DEV_DB='1'
  python manage.py test mobile_api.tests.test_job_detail_api_security --keepdb
"""
from __future__ import annotations

import uuid
from unittest import SkipTest

from django.test import override_settings
from django_tenants.utils import schema_context
from rest_framework.exceptions import AuthenticationFailed
from django.test import TransactionTestCase
from rest_framework.test import APIClient, APIRequestFactory

from mobile_api.authentication import MobileJWTAuthentication
from mobile_api.tests.job_detail_api_support import (
    JobDetailApiFixtures,
    api_auth_headers,
    api_skip_reason,
    issue_driver_access_token,
    issue_expired_access_token,
    issue_non_driver_token,
    issue_token_wrong_driver_id,
    resolve_non_driver_tenant_user,
    job_detail_api_tests_enabled,
    job_detail_api_use_dev_database,
    load_job_detail_api_fixtures,
    mobile_api_url,
    pick_api_schema,
)


_SHARED_API_FIXTURES: JobDetailApiFixtures | None = None
_SHARED_API_SCHEMA: str | None = None


class JobDetailApiSecurityBase(TransactionTestCase):
    """Shared fixtures: real tokens, real middleware, real tenant schema."""

    databases = {'default'}

    @classmethod
    def setUpClass(cls):
        global _SHARED_API_FIXTURES, _SHARED_API_SCHEMA
        from django.db import close_old_connections

        close_old_connections()
        if not job_detail_api_tests_enabled():
            raise SkipTest(api_skip_reason() or 'Job Detail API security tests disabled')
        schema = pick_api_schema()
        if _SHARED_API_SCHEMA != schema:
            _SHARED_API_SCHEMA = schema
            _SHARED_API_FIXTURES = None
        cls.tenant_schema = _SHARED_API_SCHEMA
        if not cls.tenant_schema:
            raise SkipTest('No Job Detail READY tenant schema')
        if _SHARED_API_FIXTURES is None:
            try:
                with schema_context(cls.tenant_schema):
                    _SHARED_API_FIXTURES = load_job_detail_api_fixtures(
                        cls.tenant_schema,
                    )
            except Exception as exc:
                raise SkipTest(
                    f'Job Detail API fixtures unavailable: {exc}',
                ) from exc
        cls.api_fixtures = _SHARED_API_FIXTURES
        cls.client = APIClient()
        super().setUpClass()

    def setUp(self):
        self._ctx = schema_context(self.tenant_schema)
        self._ctx.__enter__()
        self.fx: JobDetailApiFixtures = self.api_fixtures

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def _fixture_teardown(self):
        if job_detail_api_use_dev_database():
            return
        super()._fixture_teardown()

    def _tenant_hint(self, *, other: bool = False) -> str | None:
        raw = self.fx.other_tenant_hint if other else self.fx.tenant_hint
        return raw or None

    def _api_headers(self, token: str | None, *, other: bool = False) -> dict[str, str]:
        return api_auth_headers(token, tenant_hint=self._tenant_hint(other=other))

    def _driver_headers(self, *, extra_claims: dict | None = None) -> dict[str, str]:
        token = issue_driver_access_token(
            tenant_user=self.fx.tenant_user_a,
            driver=self.fx.driver_a,
            tenant_schema=self.fx.schema,
            extra_claims=extra_claims,
        )
        return self._api_headers(token)

    def _driver_b_headers(self) -> dict[str, str] | None:
        if self.fx.driver_b is None or self.fx.tenant_user_b is None:
            return None
        token = issue_driver_access_token(
            tenant_user=self.fx.tenant_user_b,
            driver=self.fx.driver_b,
            tenant_schema=self.fx.schema,
        )
        return self._api_headers(token)

    @staticmethod
    def _body(response):
        if hasattr(response, 'json'):
            try:
                return response.json()
            except Exception:
                return {}
        return {}

    @classmethod
    def _error_code(cls, response) -> str:
        data = cls._body(response).get('data') or {}
        err = data.get('error') or {}
        return str(
            data.get('error_code') or err.get('code') or data.get('code') or '',
        )

    def assert_http_unauthorized(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self._body(response).get('status'), 2)

    def assert_http_forbidden(self, response, *, min_status=0):
        self.assertEqual(response.status_code, 403)
        body = self._body(response)
        self.assertIn(body.get('status'), (0, 2, min_status))

    def assert_job_not_found(self, response):
        self.assertEqual(response.status_code, 404)
        body = self._body(response)
        self.assertEqual(body.get('status'), 0)

    def assert_auth_or_forbidden(self, response):
        """RBAC / non-driver principal — 401 (auth) or 403 (permission)."""
        self.assertIn(response.status_code, (401, 403))


class JobDetailJwtAuthenticationApiTests(JobDetailApiSecurityBase):
    """Real ``MobileJWTAuthentication`` + ``load_mobile_driver_subject`` via HTTP."""

    def test_missing_bearer_returns_401_or_403(self):
        path = mobile_api_url(f'driver/jobs/shipments/{self.fx.own_shipment_id}/')
        response = self.client.get(path, **self._api_headers(None))
        self.assertIn(response.status_code, (401, 403))

    def test_malformed_jwt_returns_401(self):
        path = mobile_api_url(f'driver/jobs/shipments/{self.fx.own_shipment_id}/')
        response = self.client.get(
            path,
            **self._api_headers('not.a.valid.jwt'),
        )
        self.assert_http_unauthorized(response)

    def test_expired_jwt_returns_401(self):
        token = issue_expired_access_token(
            tenant_user=self.fx.tenant_user_a,
            driver=self.fx.driver_a,
            tenant_schema=self.fx.schema,
        )
        path = mobile_api_url(f'driver/jobs/shipments/{self.fx.own_shipment_id}/')
        response = self.client.get(
            path,
            **self._api_headers(token),
        )
        self.assert_http_unauthorized(response)

    def test_wrong_driver_id_claim_returns_401(self):
        token = issue_token_wrong_driver_id(
            tenant_user=self.fx.tenant_user_a,
            driver=self.fx.driver_a,
            tenant_schema=self.fx.schema,
        )
        path = mobile_api_url(f'driver/jobs/shipments/{self.fx.own_shipment_id}/')
        response = self.client.get(
            path,
            **self._api_headers(token),
        )
        self.assert_http_unauthorized(response)

    def test_valid_driver_jwt_passes_authentication_layer(self):
        factory = APIRequestFactory()
        token = issue_driver_access_token(
            tenant_user=self.fx.tenant_user_a,
            driver=self.fx.driver_a,
            tenant_schema=self.fx.schema,
        )
        request = factory.get(
            '/api/v1/mobile/driver/jobs/shipments/x/',
            HTTP_AUTHORIZATION=f'Bearer {token}',
            HTTP_X_TENANT_ID=self.fx.tenant_hint,
        )
        user, payload = MobileJWTAuthentication().authenticate(request)
        self.assertIsNotNone(user)
        self.assertEqual(str(payload.get('tenant_schema')), self.fx.schema)
        self.assertEqual(
            str(payload.get('driver_id')),
            str(self.fx.driver_a.driver_id),
        )


class JobDetailTenantIsolationApiTests(JobDetailApiSecurityBase):
    """Tenant hint vs JWT schema — auth + ``MobileJobListSecurityMiddleware``."""

    def test_tenant_header_mismatch_returns_403(self):
        if not self.fx.other_tenant_hint or not self.fx.tenant_hint:
            self.skipTest('Registry tenant hints required for cross-tenant test')
        token = issue_driver_access_token(
            tenant_user=self.fx.tenant_user_a,
            driver=self.fx.driver_a,
            tenant_schema=self.fx.schema,
        )
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.own_shipment_id}/timeline/',
        )
        response = self.client.get(
            path,
            **self._api_headers(token, other=True),
        )
        self.assert_http_forbidden(response)
        body = self._body(response)
        err = (body.get('data') or {}).get('error_code') or (body.get('data') or {}).get('code')
        self.assertIn(err, ('tenant_mismatch', 'forbidden', 'unauthorized', None))

    @override_settings(MOBILE_API_JOBS_MIDDLEWARE_ENFORCE_TENANT=True)
    def test_middleware_blocks_jobs_timeline_before_view_on_tenant_mismatch(self):
        if not self.fx.other_tenant_hint or not self.fx.tenant_hint:
            self.skipTest('Registry tenant hints required')
        token = issue_driver_access_token(
            tenant_user=self.fx.tenant_user_a,
            driver=self.fx.driver_a,
            tenant_schema=self.fx.schema,
        )
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.own_shipment_id}/timeline/',
        )
        response = self.client.get(
            path,
            **self._api_headers(token, other=True),
        )
        self.assertEqual(response.status_code, 403)
        data = self._body(response).get('data') or {}
        self.assertEqual(data.get('error_code'), 'tenant_mismatch')

    def test_jwt_auth_raises_tenant_mismatch_without_matching_hint(self):
        if not self.fx.other_tenant_hint or not self.fx.tenant_hint:
            self.skipTest('Registry tenant hints required')
        factory = APIRequestFactory()
        token = issue_driver_access_token(
            tenant_user=self.fx.tenant_user_a,
            driver=self.fx.driver_a,
            tenant_schema=self.fx.schema,
        )
        request = factory.get(
            '/api/v1/mobile/driver/jobs/shipments/x/',
            HTTP_AUTHORIZATION=f'Bearer {token}',
            HTTP_X_TENANT_ID=self.fx.other_tenant_hint,
        )
        with self.assertRaises(AuthenticationFailed):
            MobileJWTAuthentication().authenticate(request)


class JobDetailRbacApiTests(JobDetailApiSecurityBase):
    """Driver RBAC — non-driver principal cannot access job detail routes."""

    def _non_driver_token(self) -> str:
        user = resolve_non_driver_tenant_user(self.fx.schema)
        return issue_non_driver_token(
            tenant_user=user,
            tenant_schema=self.fx.schema,
        )

    def test_non_driver_jwt_denied_shipment_detail(self):
        token = self._non_driver_token()
        path = mobile_api_url(f'driver/jobs/shipments/{self.fx.own_shipment_id}/')
        response = self.client.get(
            path,
            **api_auth_headers(token, tenant_hint=self.fx.tenant_hint),
        )
        self.assert_auth_or_forbidden(response)

    def test_non_driver_jwt_denied_execute(self):
        token = self._non_driver_token()
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.own_shipment_id}/actions/execute/',
        )
        response = self.client.post(
            path,
            data={'action_id': str(uuid.uuid4())},
            format='json',
            **self._api_headers(token),
        )
        self.assert_auth_or_forbidden(response)

    def test_non_driver_jwt_denied_movement_detail(self):
        token = self._non_driver_token()
        path = mobile_api_url(f'driver/jobs/movements/{self.fx.own_movement_id}/')
        response = self.client.get(
            path,
            **self._api_headers(token),
        )
        self.assert_auth_or_forbidden(response)


class JobDetailOwnershipApiTests(JobDetailApiSecurityBase):
    """Shipment / movement IDOR — scoped to authenticated driver only."""

    def test_own_shipment_detail_not_401(self):
        path = mobile_api_url(f'driver/jobs/shipments/{self.fx.own_shipment_id}/')
        response = self.client.get(path, **self._driver_headers())
        self.assertNotEqual(response.status_code, 401)
        self.assertNotEqual(response.status_code, 403)

    def test_foreign_shipment_detail_returns_404(self):
        if not self.fx.foreign_shipment_id:
            self.skipTest('No foreign shipment fixture')
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.foreign_shipment_id}/',
        )
        response = self.client.get(path, **self._driver_headers())
        self.assert_job_not_found(response)

    def test_foreign_movement_detail_returns_404(self):
        if not self.fx.foreign_movement_id:
            self.skipTest('No foreign movement fixture')
        path = mobile_api_url(
            f'driver/jobs/movements/{self.fx.foreign_movement_id}/',
        )
        response = self.client.get(path, **self._driver_headers())
        self.assert_job_not_found(response)

    def test_foreign_shipment_timeline_returns_404(self):
        if not self.fx.foreign_shipment_id:
            self.skipTest('No foreign shipment fixture')
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.foreign_shipment_id}/timeline/',
        )
        response = self.client.get(path, **self._driver_headers())
        self.assert_job_not_found(response)

    def test_foreign_shipment_allowed_actions_returns_404(self):
        if not self.fx.foreign_shipment_id:
            self.skipTest('No foreign shipment fixture')
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.foreign_shipment_id}/actions/',
        )
        response = self.client.get(path, **self._driver_headers())
        self.assert_job_not_found(response)

    def test_cross_driver_shipment_detail_returns_404(self):
        if not self.fx.foreign_shipment_id:
            self.skipTest('No second driver shipment')
        headers_b = self._driver_b_headers()
        if headers_b is None:
            self.skipTest('No second active driver')
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.foreign_shipment_id}/',
        )
        response = self.client.get(path, **headers_b)
        self.assert_job_not_found(response)


class JobDetailExecuteSecurityApiTests(JobDetailApiSecurityBase):
    """Execute POST — ownership, invalid action, cross-driver."""

    def test_execute_foreign_shipment_returns_404(self):
        if not self.fx.foreign_shipment_id:
            self.skipTest('No foreign shipment fixture')
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.foreign_shipment_id}/actions/execute/',
        )
        response = self.client.post(
            path,
            data={'action_id': str(uuid.uuid4())},
            format='json',
            **self._driver_headers(),
        )
        self.assert_job_not_found(response)

    def test_execute_invalid_action_on_own_shipment_returns_400(self):
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.own_shipment_id}/actions/execute/',
        )
        response = self.client.post(
            path,
            data={'action_id': str(uuid.uuid4())},
            format='json',
            **self._driver_headers(),
        )
        self.assertNotIn(response.status_code, (401, 403), self._body(response))
        self.assertEqual(response.status_code, 400)
        body = self._body(response)
        self.assertEqual(body.get('status'), 0)
        self.assertIn(
            self._error_code(response),
            (
                'invalid_action',
                'action_not_allowed',
                'execute_failed',
                'execution_validation_failed',
                'validation_error',
            ),
        )

    def test_cross_driver_execute_returns_404(self):
        if not self.fx.foreign_shipment_id:
            self.skipTest('No foreign shipment')
        headers_b = self._driver_b_headers()
        if headers_b is None:
            self.skipTest('No second driver')
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.own_shipment_id}/actions/execute/',
        )
        response = self.client.post(
            path,
            data={'action_id': str(uuid.uuid4())},
            format='json',
            **headers_b,
        )
        self.assert_job_not_found(response)

    @override_settings(MOBILE_API_JOBS_MIDDLEWARE_ENFORCE_TENANT=True)
    def test_middleware_allows_execute_post_method(self):
        """Execution POST must not be rejected as jobs_method_not_allowed."""
        path = mobile_api_url(
            f'driver/jobs/shipments/{self.fx.own_shipment_id}/actions/execute/',
        )
        response = self.client.post(
            path,
            data={'action_id': str(uuid.uuid4())},
            format='json',
            **self._driver_headers(),
        )
        self.assertNotEqual(response.status_code, 405)
        data = self._body(response).get('data') or {}
        self.assertNotEqual(data.get('error_code'), 'jobs_method_not_allowed')
