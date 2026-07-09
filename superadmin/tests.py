import uuid

from django.test import TestCase

from superadmin.email_uniqueness import (
    active_admin_email_conflict,
    active_tenant_email_conflict,
    admin_activation_email_blocked,
    is_admin_email_blocking,
    is_tenant_email_blocking,
    tenant_activation_email_blocked,
)
from superadmin.forms import (
    AdminUserForm,
    TenantProfileCreateForm,
    TenantProfileUpdateForm,
)
from superadmin.models import AdminUser, Role, TenantProfile


class CrossDomainEmailValidationTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.shared_email = f'shared_{suffix}@example.com'
        self.role = Role.objects.create(
            role_name_en=f'Role_{suffix}',
            role_name_ar=f'RoleAR_{suffix}',
            status='Active',
        )
        self.admin = AdminUser.objects.create(
            first_name='Super',
            last_name='Admin',
            email=self.shared_email,
            status='Active',
            role=self.role,
        )
        self.tenant = TenantProfile.objects.create(
            company_name=f'Company {suffix}',
            registration_number=f'REG-{suffix}',
            primary_email=f'tenant_{suffix}@example.com',
            primary_phone='1234567890',
            account_status='Active',
        )

    def test_admin_form_rejects_active_tenant_email(self):
        form = AdminUserForm(
            data={
                'first_name': 'Another',
                'last_name': 'Admin',
                'email': self.tenant.primary_email,
                'phone_number': '',
                'role': str(self.role.pk),
                'status': 'Active',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('already used by an active tenant admin', str(form.errors))

    def test_admin_form_allows_churned_tenant_email(self):
        self.tenant.account_status = 'Churned'
        self.tenant.save(update_fields=['account_status'])
        form = AdminUserForm(
            data={
                'first_name': 'Another',
                'last_name': 'Admin',
                'email': self.tenant.primary_email,
                'phone_number': '',
                'role': str(self.role.pk),
                'status': 'Active',
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_form_allows_suspended_tenant_email(self):
        self.tenant.account_status = 'Suspended_Billing'
        self.tenant.save(update_fields=['account_status'])
        self.assertFalse(active_tenant_email_conflict(self.tenant.primary_email))
        form = AdminUserForm(
            data={
                'first_name': 'Another',
                'last_name': 'Admin',
                'email': self.tenant.primary_email,
                'phone_number': '',
                'role': str(self.role.pk),
                'status': 'Active',
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_form_allows_soft_deleted_tenant_email(self):
        self.tenant.is_deleted = True
        self.tenant.save(update_fields=['is_deleted'])
        self.assertFalse(active_tenant_email_conflict(self.tenant.primary_email))
        form = AdminUserForm(
            data={
                'first_name': 'Another',
                'last_name': 'Admin',
                'email': self.tenant.primary_email,
                'phone_number': '',
                'role': str(self.role.pk),
                'status': 'Active',
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_tenant_create_form_rejects_active_admin_email(self):
        form = TenantProfileCreateForm(
            data={
                'company_name': 'New Co',
                'registration_number': 'REG-NEW',
                'tax_number': '',
                'primary_email': self.shared_email,
                'primary_phone': '1234567890',
                'account_status': 'Active',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('already used by an active super admin', str(form.errors))

    def test_tenant_create_form_rejects_active_admin_email_when_tenant_suspended(self):
        form = TenantProfileCreateForm(
            data={
                'company_name': 'New Co',
                'registration_number': 'REG-NEW-SUSP',
                'tax_number': '',
                'primary_email': self.shared_email,
                'primary_phone': '1234567890',
                'account_status': 'Suspended_Billing',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('already used by an active super admin', str(form.errors))

    def test_tenant_update_form_rejects_active_admin_email(self):
        form = TenantProfileUpdateForm(
            data={
                'company_name': self.tenant.company_name,
                'registration_number': self.tenant.registration_number,
                'tax_number': '',
                'primary_email': self.shared_email,
                'primary_phone': self.tenant.primary_phone,
                'account_status': 'Active',
            },
            instance=self.tenant,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('already used by an active super admin', str(form.errors))

    def test_tenant_update_rejects_active_admin_email_when_tenant_inactive(self):
        self.tenant.account_status = 'Churned'
        self.tenant.save(update_fields=['account_status'])
        form = TenantProfileUpdateForm(
            data={
                'company_name': self.tenant.company_name,
                'registration_number': self.tenant.registration_number,
                'tax_number': '',
                'primary_email': self.shared_email,
                'primary_phone': self.tenant.primary_phone,
                'account_status': 'Churned',
            },
            instance=self.tenant,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('already used by an active super admin', str(form.errors))

    def test_tenant_form_allows_suspended_admin_email(self):
        self.admin.status = 'Suspended'
        self.admin.save(update_fields=['status'])
        self.assertFalse(is_admin_email_blocking(self.admin))
        self.assertFalse(active_admin_email_conflict(self.shared_email))
        form = TenantProfileCreateForm(
            data={
                'company_name': 'New Co',
                'registration_number': 'REG-NEW-2',
                'tax_number': '',
                'primary_email': self.shared_email,
                'primary_phone': '1234567890',
                'account_status': 'Active',
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_tenant_form_allows_soft_deleted_admin_email(self):
        self.admin.is_deleted = True
        self.admin.save(update_fields=['is_deleted'])
        self.assertFalse(is_admin_email_blocking(self.admin))
        self.assertFalse(active_admin_email_conflict(self.shared_email))
        form = TenantProfileCreateForm(
            data={
                'company_name': 'New Co',
                'registration_number': 'REG-NEW-3',
                'tax_number': '',
                'primary_email': self.shared_email,
                'primary_phone': '1234567890',
                'account_status': 'Active',
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_activation_blocked_when_active_tenant_has_email(self):
        suspended_admin = AdminUser.objects.create(
            first_name='Suspended',
            last_name='Admin',
            email=self.tenant.primary_email,
            status='Suspended',
            role=self.role,
        )
        self.assertIsNone(admin_activation_email_blocked(suspended_admin))
        suspended_admin.status = 'Active'
        self.assertEqual(
            admin_activation_email_blocked(suspended_admin),
            'This email is already used by an active tenant admin.',
        )

    def test_tenant_activation_blocked_when_active_admin_has_email(self):
        self.tenant.account_status = 'Churned'
        self.tenant.primary_email = self.shared_email
        self.tenant.save(update_fields=['account_status', 'primary_email'])
        self.assertIsNone(tenant_activation_email_blocked(self.tenant))
        self.tenant.account_status = 'Active'
        self.assertEqual(
            tenant_activation_email_blocked(self.tenant),
            'This email is already used by an active super admin.',
        )


from unittest.mock import patch
import redis
from superadmin.redis_helpers import (
    reset_redis_client,
    count_active_admin_sessions,
    get_all_active_admin_sessions,
    get_all_active_tenant_sessions,
    revoke_all_sessions_for_admin,
    revoke_all_tenant_sessions,
    revoke_admin_session,
)

class RedisHelperTimeoutTests(TestCase):
    def setUp(self):
        reset_redis_client()

    def tearDown(self):
        reset_redis_client()

    @patch('superadmin.redis_helpers.get_redis_client')
    def test_count_active_admin_sessions_timeout(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.scan.side_effect = redis.exceptions.TimeoutError("Timeout connecting to server")
        
        result = count_active_admin_sessions()
        self.assertEqual(result, 0)

    @patch('superadmin.redis_helpers.get_redis_client')
    def test_get_all_active_admin_sessions_timeout(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.scan.side_effect = redis.exceptions.TimeoutError("Timeout connecting to server")
        
        result = get_all_active_admin_sessions()
        self.assertEqual(result, [])

    @patch('superadmin.redis_helpers.get_redis_client')
    def test_get_all_active_tenant_sessions_timeout(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.scan.side_effect = redis.exceptions.TimeoutError("Timeout connecting to server")
        
        result = get_all_active_tenant_sessions()
        self.assertEqual(result, [])

    @patch('superadmin.redis_helpers.get_redis_client')
    def test_revoke_all_sessions_for_admin_timeout(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.scan.side_effect = redis.exceptions.TimeoutError("Timeout connecting to server")
        
        result = revoke_all_sessions_for_admin("123")
        self.assertFalse(result)

    @patch('superadmin.redis_helpers.get_redis_client')
    def test_revoke_all_tenant_sessions_timeout(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.scan.side_effect = redis.exceptions.TimeoutError("Timeout connecting to server")
        
        result = revoke_all_tenant_sessions("tenant-uuid")
        self.assertEqual(result, 0)

    @patch('superadmin.redis_helpers.get_redis_client')
    def test_revoke_admin_session_timeout(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.delete.side_effect = redis.exceptions.TimeoutError("Timeout connecting to server")
        
        result = revoke_admin_session("jti-uuid")
        self.assertFalse(result)
