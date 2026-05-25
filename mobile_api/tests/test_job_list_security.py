"""
Tests for job list RBAC, ownership, and secure query boundaries.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.helpers.job_list_security import (
    JOBS_CAPABILITY,
    SecureJobListContext,
    assert_driver_owns_shipment,
    filter_owned_shipment_rows,
    jobs_ownership_sanitize_enabled,
    resolve_secure_job_list_context,
    sanitize_job_list_page,
    validate_jobs_tenant_binding,
)
from mobile_api.permissions import HasDriverJobsAccess
from mobile_api.rbac import CAPABILITY_GROUPS


class JobListRbacTests(SimpleTestCase):
    def test_capability_mapped_to_driver_only(self):
        self.assertEqual(CAPABILITY_GROUPS.get(JOBS_CAPABILITY), ('driver',))

    def test_has_driver_jobs_access_permission_class(self):
        self.assertEqual(
            HasDriverJobsAccess().message,
            HasDriverJobsAccess.message,
        )


class JobListOwnershipTests(SimpleTestCase):
    def test_assert_driver_owns_shipment_delegates(self):
        driver = MagicMock()
        driver.pk = uuid4()
        shipment = MagicMock()
        shipment.shipment_id = uuid4()
        shipment.pk = shipment.shipment_id

        with patch(
            'mobile_api.helpers.job_list_security.assert_shipment_row_owned',
            return_value=True,
        ) as mock_assert:
            self.assertTrue(assert_driver_owns_shipment(driver, shipment))
            mock_assert.assert_called_once()

    def test_sanitize_drops_unowned_rows(self):
        driver = MagicMock()
        driver.pk = uuid4()
        owned = MagicMock()
        owned.shipment_id = uuid4()
        owned.pk = owned.shipment_id
        foreign = MagicMock()
        foreign.shipment_id = uuid4()
        foreign.pk = foreign.shipment_id

        ctx = SecureJobListContext(
            driver=driver,
            tenant_user=MagicMock(),
            tenant_schema='tenant_a',
            driver_id=str(driver.pk),
            user_id=str(uuid4()),
            ownership_scope=None,
        )

        with patch(
            'mobile_api.helpers.job_list_security.assert_driver_owns_shipment',
            side_effect=lambda d, s, **kw: s is owned,
        ):
            safe = sanitize_job_list_page(
                [owned, foreign],
                ctx=ctx,
                entity_type='shipment',
            )
        self.assertEqual(len(safe), 1)
        self.assertIs(safe[0], owned)


class JobListSecureContextTests(SimpleTestCase):
    def test_resolve_delegates_to_dashboard_context(self):
        dash_ctx = MagicMock()
        dash_ctx.driver = MagicMock(driver_id=uuid4())
        dash_ctx.tenant_user = MagicMock()
        dash_ctx.tenant_schema = 't1'
        dash_ctx.driver_id = str(dash_ctx.driver.driver_id)
        dash_ctx.user_id = str(uuid4())
        dash_ctx.jwt_driver_id = None

        with patch(
            'mobile_api.helpers.job_list_security.resolve_secure_dashboard_context',
            return_value={'success': True, 'ctx': dash_ctx},
        ):
            with patch(
                'mobile_api.helpers.job_list_security.jobs_ownership_sanitize_enabled',
                return_value=False,
            ):
                out = resolve_secure_job_list_context(
                    user_id=dash_ctx.user_id,
                    tenant_schema='t1',
                )
        self.assertTrue(out['success'])
        self.assertIsInstance(out['ctx'], SecureJobListContext)

    def test_validate_jobs_tenant_binding_delegates(self):
        request = MagicMock()
        with patch(
            'mobile_api.helpers.job_list_security.validate_dashboard_tenant_binding',
            return_value=True,
        ) as mock_v:
            self.assertTrue(
                validate_jobs_tenant_binding(request, expected_schema='t1'),
            )
            mock_v.assert_called_once()
