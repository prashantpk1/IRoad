"""
Tests for driver job execution security (RBAC, ownership, action guards).
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings

from mobile_api.helpers.job_execution_security import (
    JOBS_EXECUTE_CAPABILITY,
    SecureJobExecutionContext,
    authorize_driver_action_execution,
    execution_context_required_error,
    is_jobs_execution_post_path,
    jobs_execution_action_membership_enabled,
    require_execution_context,
    secure_lookup_operation_action,
    strip_execution_audit_tamper_fields,
)
from mobile_api.helpers.mobile_execution_guard import (
    MobileExecutionGuardError,
    assert_mobile_execution_guard_allows,
    mobile_execution_guard,
)
from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
from mobile_api.middleware import MobileJobListSecurityMiddleware
from mobile_api.permissions import HasDriverJobsExecuteAccess
from mobile_api.rbac import CAPABILITY_GROUPS


class JobExecutionRbacTests(SimpleTestCase):
    def test_execute_capability_mapped_to_driver(self):
        self.assertEqual(
            CAPABILITY_GROUPS.get(JOBS_EXECUTE_CAPABILITY),
            ('driver',),
        )

    def test_has_driver_jobs_execute_access_class(self):
        self.assertEqual(
            HasDriverJobsExecuteAccess().message,
            HasDriverJobsExecuteAccess.message,
        )


class JobExecutionPathTests(SimpleTestCase):
    def test_execution_post_paths_detected(self):
        sid = uuid4()
        self.assertTrue(
            is_jobs_execution_post_path(
                f'/api/v1/mobile/driver/jobs/shipments/{sid}/actions/execute/',
            ),
        )
        self.assertTrue(
            is_jobs_execution_post_path(
                f'/api/v1/mobile/driver/jobs/shipments/{sid}/upload-pod/',
            ),
        )
        self.assertFalse(
            is_jobs_execution_post_path(
                f'/api/v1/mobile/driver/jobs/shipments/{sid}/',
            ),
        )


class JobExecutionGuardTests(SimpleTestCase):
    def test_strip_audit_tamper_fields(self):
        body = strip_execution_audit_tamper_fields({
            'notes': 'ok',
            'driver_id': 'evil',
            'log_id': 'evil',
        })
        self.assertEqual(body, {'notes': 'ok'})

    @override_settings(DEBUG=True, MOBILE_API_JOBS_ENFORCE_ACTION_MEMBERSHIP=False)
    def test_membership_check_disabled_only_in_debug(self):
        self.assertFalse(jobs_execution_action_membership_enabled())

    @override_settings(DEBUG=False, MOBILE_API_JOBS_ENFORCE_ACTION_MEMBERSHIP=False)
    def test_membership_mandatory_in_production_even_if_setting_false(self):
        self.assertTrue(jobs_execution_action_membership_enabled())
        action = MagicMock()
        action.pk = uuid4()
        action.action_code = 'A5'
        ctx = SecureJobExecutionContext(
            driver=MagicMock(pk=uuid4()),
            tenant_user=MagicMock(),
            tenant_schema='t1',
            driver_id=str(uuid4()),
            user_id=str(uuid4()),
        )
        with patch(
            'mobile_api.helpers.job_execution_security._allowed_action_id_set',
            return_value={str(action.pk)},
        ):
            with patch(
                'iroad_tenants.services.operation_execution_service.OperationExecutionService.validate_driver_action_execution',
                return_value=None,
            ):
                out = authorize_driver_action_execution(
                    action,
                    ctx=ctx,
                    shipment=MagicMock(),
                    movement=None,
                )
        self.assertTrue(out.get('success'))

    def test_secure_lookup_rejects_inactive_action(self):
        ctx = SecureJobExecutionContext(
            driver=MagicMock(),
            tenant_user=MagicMock(),
            tenant_schema='t1',
            driver_id=str(uuid4()),
            user_id=str(uuid4()),
        )
        with patch(
            'mobile_api.helpers.job_execution_security.TenantOperationAction.objects',
        ) as qs:
            qs.filter.return_value.first.return_value = None
            with patch(
                'mobile_api.helpers.job_execution_security.jobs_execution_audit_enabled',
                return_value=False,
            ):
                row = secure_lookup_operation_action(uuid4(), ctx=ctx)
        self.assertIsNone(row)


class ExecutionContextMandatoryTests(SimpleTestCase):
    def test_require_execution_context_rejects_none(self):
        err = require_execution_context(None)
        self.assertIsNotNone(err)
        self.assertEqual(err['code'], 'execution_context_required')

    def test_secure_lookup_requires_context(self):
        err = execution_context_required_error()
        self.assertEqual(err['code'], 'execution_context_required')
        row = secure_lookup_operation_action(
            uuid4(),
            ctx=None,  # type: ignore[arg-type]
        )
        self.assertIsNone(row)

    def test_mobile_guard_missing_raises(self):
        with self.assertRaises(MobileExecutionGuardError):
            assert_mobile_execution_guard_allows(
                source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
            )

    def test_mobile_guard_active_matches_driver(self):
        driver_pk = uuid4()
        ctx = SecureJobExecutionContext(
            driver=MagicMock(pk=driver_pk),
            tenant_user=MagicMock(),
            tenant_schema='t_test',
            driver_id=str(driver_pk),
            user_id=str(uuid4()),
        )
        with mobile_execution_guard(ctx):
            bound = assert_mobile_execution_guard_allows(
                driver=ctx.driver,
                source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
            )
        self.assertIs(bound, ctx)

    def test_mobile_guard_driver_mismatch_raises(self):
        ctx = SecureJobExecutionContext(
            driver=MagicMock(pk=uuid4()),
            tenant_user=MagicMock(),
            tenant_schema='t_test',
            driver_id=str(uuid4()),
            user_id=str(uuid4()),
        )
        other_driver = MagicMock(pk=uuid4())
        with mobile_execution_guard(ctx):
            with self.assertRaises(MobileExecutionGuardError):
                assert_mobile_execution_guard_allows(
                    driver=other_driver,
                    source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                )


class JobExecutionMiddlewareTests(SimpleTestCase):
    def test_post_execute_not_blocked_as_unsafe_method(self):
        """Execution POST must not receive jobs_method_not_allowed 405."""
        shipment_id = uuid4()
        path = f'/api/v1/mobile/driver/jobs/shipments/{shipment_id}/actions/execute/'

        request = MagicMock()
        request.path = path
        request.method = 'POST'
        request.headers = MagicMock()
        request.headers.get.return_value = ''

        mw = MobileJobListSecurityMiddleware(lambda r: MagicMock(status_code=200))
        with patch.object(mw, 'get_response') as mock_resp:
            mock_resp.return_value = MagicMock(status_code=200)
            response = mw(request)

        self.assertEqual(response.status_code, 200)
