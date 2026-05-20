"""
mobile_api/serializers/driver_auth.py

Serializers for Driver Authentication APIs.
Input validation only — no model binding.
"""
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _


class DriverLoginSerializer(serializers.Serializer):
    """
    Validates login input.
    API 1: POST /api/v1/mobile/driver/auth/login/

    Optional ``tenant_id`` (subscriber UUID or ``schema_name``) only when the same
    email/password exists on more than one active tenant. Otherwise the tenant is
    discovered from credentials alone (login does **not** use ``X-Tenant-ID``).

    Device fields (mobile clients):
      ``device_id`` — Firebase Cloud Messaging (FCM) registration token.
      ``device_platform`` — OS family, e.g. ``iOS`` or ``Android``.
      ``device_name`` — Human-readable model, e.g. ``iPhone 16``, ``Samsung Galaxy S24``.
    """
    email = serializers.EmailField(
        required=True,
        error_messages={
            'required': _('mobile.auth.email_required'),
            'invalid': _('mobile.auth.email_invalid'),
        }
    )
    password = serializers.CharField(
        required=True,
        min_length=1,
        write_only=True,
        style={'input_type': 'password'},
        error_messages={
            'required': _('mobile.auth.password_required'),
            'blank': _('mobile.auth.password_required'),
        }
    )
    tenant_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        write_only=True,
    )
    device_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2048,
        write_only=True,
    )
    device_platform = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=32,
        write_only=True,
    )
    device_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=256,
        write_only=True,
    )

    def validate_email(self, value: str) -> str:
        return (value or '').strip().lower()


class DriverRefreshSerializer(serializers.Serializer):
    """
    Validates refresh rotation input.
    POST /api/v1/mobile/driver/auth/refresh/

    Send the **refresh** JWT in the body (preferred for mobile clarity).
    ``Authorization: Bearer <refresh>`` is accepted as a fallback when the
    body field is empty.

    Optional ``tenant_id`` when you send an explicit subscriber hint; if omitted,
    the refresh token's embedded ``tenant_schema`` is used (no ``X-Tenant-ID``
    required for the same tenant).
    """
    refresh_token = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        max_length=8000,
    )
    tenant_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        write_only=True,
    )


class ForgotPasswordSerializer(serializers.Serializer):
    """
    Validates forgot password input.
    API 2: POST /api/v1/mobile/driver/auth/forgot-password/

    ``tenant_id`` (subscriber UUID or ``schema_name``) disambiguates the tenant
    when the same email exists on multiple subscribers (recommended).
    """
    email = serializers.EmailField(
        required=True,
        error_messages={
            'required': _('mobile.auth.email_required'),
            'invalid': _('mobile.auth.email_invalid'),
        }
    )
    tenant_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        write_only=True,
    )


class VerifyOtpSerializer(serializers.Serializer):
    """
    Validates OTP verification input.
    API 3: POST /api/v1/mobile/driver/auth/verify-otp/

    ``tenant_id`` identifies which subscriber issued the OTP when needed.
    """
    email = serializers.EmailField(
        required=True,
        error_messages={
            'required': _('mobile.auth.email_required'),
            'invalid': _('mobile.auth.email_invalid'),
        }
    )
    otp_code = serializers.CharField(
        required=True,
        min_length=6,
        max_length=6,
        error_messages={
            'required': _('mobile.auth.otp_required'),
            'min_length': _('mobile.auth.otp_invalid_length'),
            'max_length': _('mobile.auth.otp_invalid_length'),
        }
    )

    def validate_otp_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError(
                _('mobile.auth.otp_digits_only')
            )
        return value

    tenant_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        write_only=True,
    )


class ResetPasswordSerializer(serializers.Serializer):
    """
    Validates new password input.
    API 4: POST /api/v1/mobile/driver/auth/reset-password/

    ``tenant_id`` identifies which subscriber holds the verified OTP.
    """
    email = serializers.EmailField(
        required=True,
        error_messages={
            'required': _('mobile.auth.email_required'),
            'invalid': _('mobile.auth.email_invalid'),
        }
    )
    otp_code = serializers.CharField(
        required=True,
        min_length=6,
        max_length=6,
        error_messages={
            'required': _('mobile.auth.otp_required'),
        }
    )
    new_password = serializers.CharField(
        required=True,
        min_length=8,
        write_only=True,
        style={'input_type': 'password'},
        error_messages={
            'required': _('mobile.auth.password_required'),
            'min_length': _('mobile.auth.password_min_length'),
        }
    )
    confirm_password = serializers.CharField(
        required=True,
        min_length=8,
        write_only=True,
        style={'input_type': 'password'},
        error_messages={
            'required': _('mobile.auth.confirm_password_required'),
        }
    )

    def validate(self, data):
        if data.get('new_password') != data.get('confirm_password'):
            raise serializers.ValidationError({
                'confirm_password':
                    _('mobile.auth.passwords_do_not_match')
            })
        return data

    def validate_otp_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError(
                _('mobile.auth.otp_digits_only')
            )
        return value

    tenant_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        write_only=True,
    )


class LogoutSerializer(serializers.Serializer):
    """
    Logout — access token comes from Authorization header.

    Optional ``refresh_token`` revokes the active refresh JTI and clears the
    refresh family binding in Redis (recommended for full session teardown).

    API 5: POST /api/v1/mobile/driver/auth/logout/
    """
    refresh_token = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        max_length=8000,
    )


class DeleteAccountSerializer(serializers.Serializer):
    """
    Validates delete-account request body (current password for confirmation).

    Checks only presence / non-blank input. Matching ``password_hash`` and
    soft-delete side effects belong in the service layer.
    """
    password = serializers.CharField(
        required=True,
        min_length=1,
        write_only=True,
        style={'input_type': 'password'},
        error_messages={
            'required': _('mobile.auth.password_required'),
            'blank': _('mobile.auth.password_required'),
            'null': _('mobile.auth.password_required'),
        },
    )
