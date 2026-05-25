"""
Regression tests for MobileJobListSecurityMiddleware.
"""
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from mobile_api.helpers.job_execution_security import is_jobs_execution_post_path
from mobile_api.helpers.middleware_request_sim import build_minimal_legacy_fake_request
from mobile_api.middleware import MobileJobListSecurityMiddleware, _jobs_finish_request


class JobsMiddlewarePathTests(SimpleTestCase):
    def test_execution_post_paths(self):
        self.assertTrue(
            is_jobs_execution_post_path(
                '/api/v1/mobile/driver/jobs/shipments/x/actions/execute/',
            ),
        )


class JobsMiddlewareFinishTests(SimpleTestCase):
    def test_finish_request_no_time_nameerror(self):
        factory = RequestFactory()
        request = factory.post(
            '/api/v1/mobile/driver/jobs/shipments/00000000-0000-0000-0000-000000000001/actions/execute/',
        )

        def get_response(req):
            return HttpResponse('ok', status=200)

        mw = MobileJobListSecurityMiddleware(get_response)
        response = mw(request)
        self.assertEqual(response.status_code, 200)

    def test_jobs_finish_helper_direct(self):
        factory = RequestFactory()
        request = factory.get(
            '/api/v1/mobile/driver/jobs/shipments/00000000-0000-0000-0000-000000000001/timeline/',
        )
        mw = MobileJobListSecurityMiddleware(lambda r: HttpResponse('ok'))
        response = _jobs_finish_request(mw, request, 0.0)
        self.assertEqual(response.status_code, 200)

    def test_finish_helper_legacy_fake_without_method(self):
        """Regression: readiness-style fakes must not trigger metrics_error."""

        class PathOnlyFake:
            path = (
                '/api/v1/mobile/driver/jobs/shipments/'
                '00000000-0000-0000-0000-000000000001/timeline/'
            )

        request = PathOnlyFake()
        mw = MobileJobListSecurityMiddleware(lambda r: HttpResponse('ok'))
        with self.assertNoLogs('mobile_api', level='ERROR'):
            response = _jobs_finish_request(mw, request, 0.0)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.method, 'GET')
