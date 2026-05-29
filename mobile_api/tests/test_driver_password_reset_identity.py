"""Password-reset identity + serializer tests (email and phone)."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework import serializers as drf_serializers

from mobile_api.helpers.driver_identity import (
    DriverAuthIdentity,
    resolve_canonical_email_for_identity,
    validate_email_or_phone_identity_data,
)
from mobile_api.serializers.driver_auth import (
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    VerifyOtpSerializer,
)
from mobile_api.models import DriverPasswordResetOTP


class PasswordResetSerializerTests(SimpleTestCase):
    def test_forgot_password_email_only(self):
        s = ForgotPasswordSerializer(data={'email': 'user@example.com'})
        self.assertTrue(s.is_valid(), s.errors)

    def test_forgot_password_phone_only_rejected_without_extension(self):
        s = ForgotPasswordSerializer(data={'phone': '9876543210'})
        self.assertFalse(s.is_valid())

    def test_forgot_password_phone_with_extension(self):
        s = ForgotPasswordSerializer(
            data={
                'extension': '+91',
                'phone': '9876543210',
            },
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_forgot_password_rejects_empty(self):
        s = ForgotPasswordSerializer(data={})
        self.assertFalse(s.is_valid())

    def test_verify_otp_phone_format(self):
        s = VerifyOtpSerializer(
            data={
                'extension': '+966',
                'phone': '963258741',
                'otp_code': '123456',
            },
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_reset_password_invalid_otp_digits(self):
        s = ResetPasswordSerializer(
            data={
                'email': 'user@example.com',
                'otp_code': 'abcdef',
                'new_password': 'Test@1234',
                'confirm_password': 'Test@1234',
            },
        )
        self.assertFalse(s.is_valid())

    def test_reset_password_phone_format(self):
        s = ResetPasswordSerializer(
            data={
                'extension': '+966',
                'phone': '963258741',
                'otp_code': '123456',
                'new_password': 'Test@1234',
                'confirm_password': 'Test@1234',
            },
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_forgot_password_rejects_both_email_and_phone(self):
        s = ForgotPasswordSerializer(
            data={
                'email': 'user@example.com',
                'extension': '+91',
                'phone': '9876543210',
            },
        )
        self.assertFalse(s.is_valid())


class PasswordResetServiceTests(SimpleTestCase):
    def test_resolve_canonical_email_from_phone(self):
        user = SimpleNamespace(email='driver@example.com')
        with patch(
            'mobile_api.helpers.driver_identity.get_driver_user_by_phone',
            return_value=user,
        ):
            identity = DriverAuthIdentity(
                phone='963258741',
                extension='+966',
            )
            email = resolve_canonical_email_for_identity(
                identity,
                'tenant_test',
            )
        self.assertEqual(email, 'driver@example.com')

    @patch('mobile_api.services.driver_auth_service.send_driver_reset_otp_email')
    @patch('mobile_api.services.driver_auth_service.DriverPasswordResetOTP')
    @patch('mobile_api.services.driver_auth_service.get_driver_master_by_user')
    @patch('mobile_api.services.driver_auth_service.get_driver_user_by_email')
    @patch(
        'mobile_api.services.driver_auth_service.resolve_canonical_email_for_identity',
        return_value='driver@example.com',
    )
    @patch('mobile_api.helpers.password_reset_security.forgot_password_rate_allow')
    def test_forgot_password_email_path(
        self,
        rate_allow,
        _resolve_email,
        get_user,
        get_driver,
        otp_model,
        send_email,
    ):
        from mobile_api.services.driver_auth_service import driver_forgot_password

        rate_allow.return_value = True
        get_user.return_value = SimpleNamespace(
            pk='u1',
            email='driver@example.com',
            full_name='Driver',
            is_deleted=False,
        )
        get_driver.return_value = SimpleNamespace(driver_status='Active')
        otp_model.resend_is_throttled.return_value = False
        send_email.return_value = True

        identity = DriverAuthIdentity(email='driver@example.com')
        result = driver_forgot_password(
            tenant_schema='tenant_test',
            identity=identity,
        )
        self.assertTrue(result['success'])
        otp_model.create_for_email.assert_called_once()

    @patch('mobile_api.helpers.password_reset_security.forgot_password_rate_allow')
    @patch('mobile_api.services.driver_auth_service.send_driver_reset_otp_email')
    @patch('mobile_api.services.driver_auth_service.DriverPasswordResetOTP')
    @patch('mobile_api.services.driver_auth_service.get_driver_master_by_user')
    @patch('mobile_api.services.driver_auth_service.get_driver_user_by_email')
    @patch(
        'mobile_api.services.driver_auth_service.resolve_canonical_email_for_identity',
        return_value='driver@example.com',
    )
    def test_forgot_password_phone_path(
        self,
        _resolve_email,
        get_user,
        get_driver,
        otp_model,
        send_email,
        rate_allow,
    ):
        from mobile_api.services.driver_auth_service import driver_forgot_password

        rate_allow.return_value = True
        get_user.return_value = SimpleNamespace(
            pk='u1',
            email='driver@example.com',
            full_name='Driver',
            is_deleted=False,
        )
        get_driver.return_value = SimpleNamespace(driver_status='Active')
        otp_model.resend_is_throttled.return_value = False
        send_email.return_value = True

        identity = DriverAuthIdentity(phone='963258741', extension='+966')
        result = driver_forgot_password(
            tenant_schema='tenant_test',
            identity=identity,
        )
        self.assertTrue(result['success'])
        otp_model.create_for_email.assert_called_once()
        call_kwargs = otp_model.create_for_email.call_args.kwargs
        self.assertEqual(call_kwargs['email'], 'driver@example.com')
        self.assertEqual(call_kwargs['tenant_schema'], 'tenant_test')

    @patch('mobile_api.helpers.password_reset_security.forgot_password_rate_allow')
    @patch('mobile_api.services.driver_auth_service.get_driver_user_by_email')
    @patch(
        'mobile_api.services.driver_auth_service.resolve_canonical_email_for_identity',
        return_value='',
    )
    def test_forgot_password_unknown_user(
        self,
        _resolve_email,
        get_user,
        rate_allow,
    ):
        from mobile_api.services.driver_auth_service import driver_forgot_password

        rate_allow.return_value = True
        get_user.return_value = None
        identity = DriverAuthIdentity(email='unknown@example.com')
        result = driver_forgot_password(
            tenant_schema='tenant_test',
            identity=identity,
        )
        self.assertTrue(result['success'])
        self.assertFalse(result['email_dispatch_status'])

    @patch('mobile_api.services.driver_auth_service.schema_context')
    @patch('mobile_api.services.driver_auth_service.DriverPasswordResetOTP')
    @patch(
        'mobile_api.services.driver_auth_service.resolve_canonical_email_for_identity',
        return_value='driver@example.com',
    )
    @patch('mobile_api.helpers.password_reset_security.verify_otp_rate_allow')
    def test_verify_otp_invalid_code(
        self,
        rate_allow,
        _resolve_email,
        otp_model,
        _schema_ctx,
    ):
        from mobile_api.services.driver_auth_service import driver_verify_otp

        rate_allow.return_value = True
        record = MagicMock()
        record.otp_code = '999999'
        record.attempts = 0
        record.is_expired = False
        otp_model.get_valid_otp.return_value = record
        otp_model.Status = DriverPasswordResetOTP.Status

        identity = DriverAuthIdentity(email='driver@example.com')
        with patch(
            'mobile_api.helpers.password_reset_security.otp_compare_constant_time',
            return_value=False,
        ):
            result = driver_verify_otp(
                otp_code='123456',
                tenant_schema='tenant_test',
                identity=identity,
            )
        self.assertFalse(result['success'])
        self.assertEqual(result['error_code'], 'otp_verify_failed')

    @patch('mobile_api.services.driver_auth_service.schema_context')
    @patch('mobile_api.services.driver_auth_service.DriverPasswordResetOTP')
    @patch(
        'mobile_api.services.driver_auth_service.resolve_canonical_email_for_identity',
        return_value='driver@example.com',
    )
    @patch('mobile_api.helpers.password_reset_security.verify_otp_rate_allow')
    def test_verify_otp_expired(
        self,
        rate_allow,
        _resolve_email,
        otp_model,
        _schema_ctx,
    ):
        from mobile_api.services.driver_auth_service import driver_verify_otp

        rate_allow.return_value = True
        record = MagicMock()
        record.otp_code = '123456'
        record.attempts = 0
        record.is_expired = True
        otp_model.get_valid_otp.return_value = record
        otp_model.Status = DriverPasswordResetOTP.Status

        identity = DriverAuthIdentity(email='driver@example.com')
        result = driver_verify_otp(
            otp_code='123456',
            tenant_schema='tenant_test',
            identity=identity,
        )
        self.assertFalse(result['success'])

    @patch('mobile_api.helpers.password_reset_security.verify_otp_rate_allow')
    @patch('mobile_api.services.driver_auth_service.schema_context')
    @patch('mobile_api.services.driver_auth_service.DriverPasswordResetOTP')
    @patch(
        'mobile_api.services.driver_auth_service.resolve_canonical_email_for_identity',
        return_value='driver@example.com',
    )
    def test_verify_otp_phone_path_success(
        self,
        _resolve_email,
        otp_model,
        _schema_ctx,
        rate_allow,
    ):
        from mobile_api.services.driver_auth_service import driver_verify_otp

        rate_allow.return_value = True
        record = MagicMock()
        record.otp_code = '123456'
        record.attempts = 0
        record.is_expired = False
        otp_model.get_valid_otp.return_value = record
        otp_model.Status = DriverPasswordResetOTP.Status

        identity = DriverAuthIdentity(phone='963258741', extension='+966')
        result = driver_verify_otp(
            otp_code='123456',
            tenant_schema='tenant_test',
            identity=identity,
        )
        self.assertTrue(result['success'])

    @patch('tenant_workspace.models.TenantUser')
    @patch('mobile_api.helpers.password_reset_security.reset_password_rate_allow')
    @patch('mobile_api.services.driver_auth_service.schema_context')
    @patch('mobile_api.services.driver_auth_service.DriverPasswordResetOTP')
    @patch('mobile_api.services.driver_auth_service.get_driver_user_by_email')
    @patch(
        'mobile_api.services.driver_auth_service.resolve_canonical_email_for_identity',
        return_value='driver@example.com',
    )
    def test_reset_password_success_email(
        self,
        _resolve_email,
        get_user,
        otp_model,
        _schema_ctx,
        rate_allow,
        tenant_user_model,
    ):
        from mobile_api.services.driver_auth_service import driver_reset_password

        rate_allow.return_value = True
        get_user.return_value = SimpleNamespace(pk='u1', is_deleted=False)
        record = MagicMock()
        record.otp_code = '123456'
        record.is_expired = False
        otp_model.get_verified_otp.return_value = record
        otp_model.Status = DriverPasswordResetOTP.Status
        otp_model.objects.filter.return_value.update.return_value = 1
        tenant_user_model.all_objects.filter.return_value.update.return_value = 1

        identity = DriverAuthIdentity(email='driver@example.com')
        with patch(
            'mobile_api.helpers.password_reset_security.otp_compare_constant_time',
            return_value=True,
        ):
            result = driver_reset_password(
                otp_code='123456',
                new_password='Test@1234',
                tenant_schema='tenant_test',
                identity=identity,
            )
        self.assertTrue(result['success'])

    @patch('mobile_api.helpers.password_reset_security.reset_password_rate_allow')
    @patch('mobile_api.services.driver_auth_service.schema_context')
    @patch('mobile_api.services.driver_auth_service.DriverPasswordResetOTP')
    @patch(
        'mobile_api.services.driver_auth_service.resolve_canonical_email_for_identity',
        return_value='driver@example.com',
    )
    def test_reset_password_invalid_otp(
        self,
        _resolve_email,
        otp_model,
        _schema_ctx,
        rate_allow,
    ):
        from mobile_api.services.driver_auth_service import driver_reset_password

        rate_allow.return_value = True
        otp_model.get_verified_otp.return_value = None
        identity = DriverAuthIdentity(email='driver@example.com')
        result = driver_reset_password(
            otp_code='000000',
            new_password='Test@1234',
            tenant_schema='tenant_test',
            identity=identity,
        )
        self.assertFalse(result['success'])
        self.assertEqual(result['error_code'], 'reset_password_failed')
