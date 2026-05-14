"""
mobile_api/serializers/driver_profile.py

Serializers for driver profile read/update and authenticated change-password flow.

Input serializers: validation only (no DB password checks here).
Output: DriverProfileSerializer builds a read-only envelope from model instances
passed in ``instance`` (see ``DriverProfileSerializer`` docstring).
"""
from __future__ import annotations

import os
from typing import Any

from django.conf import settings
from django.core.files.images import get_image_dimensions
from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext

from mobile_api.serializers.localized import (
    LocalizedSerializerMixin,
    serialize_localized_label,
    serialize_localized_name,
)

# Max upload size aligned with DriverAttachment.ATTACHMENT_MAX_SIZE_MB (10 MB).
PROFILE_PHOTO_MAX_SIZE_BYTES = 10 * 1024 * 1024

PROFILE_PHOTO_ALLOWED_EXTENSIONS = frozenset({
    '.jpg', '.jpeg', '.png', '.webp',
})


def safe_media_url(request, file_obj) -> str | None:
    """
    Build an absolute media URL when possible; return None if missing or invalid.

    Never raises for absent files (null-safe).
    """
    if not file_obj:
        return None
    name = getattr(file_obj, 'name', None)
    if not name:
        return None
    try:
        url = file_obj.url
    except (ValueError, AttributeError):
        return None
    if not url:
        return None
    if request is not None:
        try:
            return request.build_absolute_uri(url)
        except Exception:
            pass
    # Relative URL (caller may still resolve against known host)
    if url.startswith('http://') or url.startswith('https://'):
        return url
    media_url = getattr(settings, 'MEDIA_URL', '/media/')
    if url.startswith('/'):
        pass
    elif media_url and not url.startswith(media_url):
        url = f'{media_url.rstrip("/")}/{url.lstrip("/")}'
    return url


CHANGE_PASSWORD_SEND_VIA_CHOICES = (
    ('email', 'email'),
    ('mobile', 'mobile'),
)


class DriverRequestChangePasswordOtpSerializer(serializers.Serializer):
    """
    Request OTP for authenticated change-password flow.

    Authenticated driver checks belong in the service layer.
    """

    send_via = serializers.ChoiceField(
        choices=CHANGE_PASSWORD_SEND_VIA_CHOICES,
        required=True,
        error_messages={
            'required': _('mobile.profile.send_via_required'),
            'invalid_choice': _('mobile.profile.send_via_invalid'),
        },
    )


class DriverVerifyChangePasswordOtpSerializer(serializers.Serializer):
    """
    Verify change-password OTP (same digit rules as VerifyOtpSerializer).
    """

    otp_code = serializers.CharField(
        required=True,
        min_length=6,
        max_length=6,
        error_messages={
            'required': _('mobile.auth.otp_required'),
            'min_length': _('mobile.auth.otp_invalid_length'),
            'max_length': _('mobile.auth.otp_invalid_length'),
        },
    )

    def validate_otp_code(self, value: str) -> str:
        if not value.isdigit():
            raise serializers.ValidationError(
                _('mobile.auth.otp_digits_only')
            )
        return value


class DriverChangePasswordSerializer(serializers.Serializer):
    """
    Change password after OTP verification.

    Password verification against DB is performed in the service layer only.
    """

    current_password = serializers.CharField(
        required=True,
        min_length=1,
        max_length=128,
        write_only=True,
        style={'input_type': 'password'},
        error_messages={
            'required': _('mobile.profile.current_password_required'),
            'blank': _('mobile.profile.current_password_blank'),
            'null': _('mobile.profile.current_password_required'),
            'max_length': _('mobile.validation.password_too_long'),
        },
    )
    new_password = serializers.CharField(
        required=True,
        min_length=8,
        max_length=128,
        write_only=True,
        style={'input_type': 'password'},
        error_messages={
            'required': _('mobile.auth.password_required'),
            'min_length': _('mobile.auth.password_min_length'),
            'max_length': _('mobile.validation.password_too_long'),
        },
    )
    confirm_password = serializers.CharField(
        required=True,
        min_length=8,
        max_length=128,
        write_only=True,
        style={'input_type': 'password'},
        error_messages={
            'required': _('mobile.auth.confirm_password_required'),
            'min_length': _('mobile.auth.password_min_length'),
            'max_length': _('mobile.validation.password_too_long'),
        },
    )
    otp_code = serializers.CharField(
        required=True,
        min_length=6,
        max_length=6,
        error_messages={
            'required': _('mobile.auth.otp_required'),
            'min_length': _('mobile.auth.otp_invalid_length'),
            'max_length': _('mobile.auth.otp_invalid_length'),
        },
    )

    def validate_current_password(self, value: str) -> str:
        if not (value or '').strip():
            raise serializers.ValidationError(
                _('mobile.profile.current_password_blank')
            )
        return value

    def validate_new_password(self, value: str) -> str:
        if not (value or '').strip():
            raise serializers.ValidationError(
                _('mobile.auth.password_required')
            )
        return value

    def validate_confirm_password(self, value: str) -> str:
        if not (value or '').strip():
            raise serializers.ValidationError(
                _('mobile.auth.confirm_password_required')
            )
        return value

    def validate_otp_code(self, value: str) -> str:
        if not value.isdigit():
            raise serializers.ValidationError(
                _('mobile.auth.otp_digits_only')
            )
        return value

    def validate(self, data: dict) -> dict:
        if data.get('new_password') != data.get('confirm_password'):
            raise serializers.ValidationError({
                'confirm_password': _(
                    'mobile.auth.passwords_do_not_match'
                ),
            })
        return data


class DriverProfilePhotoUpdateSerializer(serializers.Serializer):
    """
    Multipart upload for driver profile photo (Phase 1 may map to dl_image in service).

    Images only: jpg, jpeg, png, webp — no documents.
    """

    profile_photo = serializers.ImageField(
        required=True,
        allow_empty_file=False,
        error_messages={
            'required': _('mobile.profile.photo_required'),
            'invalid_image': _('mobile.validation.invalid_image'),
        },
    )

    def validate_profile_photo(self, value):
        name = getattr(value, 'name', '') or ''
        ext = os.path.splitext(name)[1].lower()
        if ext not in PROFILE_PHOTO_ALLOWED_EXTENSIONS:
            raise serializers.ValidationError(
                _('mobile.validation.invalid_image')
            )
        size = getattr(value, 'size', None)
        if size is not None and size > PROFILE_PHOTO_MAX_SIZE_BYTES:
            size_mb = round(size / 1024 / 1024, 1)
            max_mb = PROFILE_PHOTO_MAX_SIZE_BYTES // (1024 * 1024)
            raise serializers.ValidationError(
                gettext('mobile.validation.image_too_large')
                % {'max_mb': max_mb, 'size_mb': size_mb}
            )
        content_type = getattr(value, 'content_type', '') or ''
        if content_type and not content_type.startswith('image/'):
            raise serializers.ValidationError(
                _('mobile.validation.invalid_image')
            )
        try:
            if hasattr(value, 'seek'):
                value.seek(0)
            get_image_dimensions(value)
        except Exception:
            raise serializers.ValidationError(
                _('mobile.validation.invalid_image')
            )
        finally:
            if hasattr(value, 'seek'):
                try:
                    value.seek(0)
                except Exception:
                    pass
        return value


def _nationality_code(driver) -> str | None:
    country = getattr(driver, 'nationality_country', None)
    if country is None:
        return None
    return getattr(country, 'country_code', None) or None


def _serialize_driver_section(driver, request) -> dict[str, Any]:
    if driver is None:
        return {
            'driver_id': None,
            'driver_code': None,
            **serialize_localized_name(request, None, None),
            'driver_status': None,
            'driver_source': None,
            'driver_type': None,
            'nationality': None,
            'birth_date': None,
            'mobile_number': None,
            'whatsapp_number': None,
        }
    return {
        'driver_id': str(driver.driver_id),
        'driver_code': driver.driver_code,
        **serialize_localized_name(
            request,
            english_value=driver.english_name or '',
            arabic_value=driver.arabic_name,
        ),
        'driver_status': driver.driver_status,
        'driver_source': driver.driver_source,
        'driver_type': driver.driver_type or '',
        'nationality': _nationality_code(driver),
        'birth_date': driver.birth_date,
        'mobile_number': driver.mobile_number,
        'whatsapp_number': driver.whatsapp_number or '',
    }


def _serialize_tenant_user_section(tenant_user, request) -> dict[str, Any]:
    """Expose only client-safe fields (no password_hash, login_attempts, etc.)."""
    if tenant_user is None:
        return {
            'username': None,
            'full_name': None,
            'email': None,
            'mobile_country_code': None,
            'mobile_no': None,
            'role_name': None,
        }
    return {
        'username': tenant_user.username,
        'full_name': tenant_user.full_name,
        'email': tenant_user.email,
        'mobile_country_code': tenant_user.mobile_country_code or '',
        'mobile_no': tenant_user.mobile_no or '',
        'role_name': tenant_user.role_name,
    }


def _serialize_truck_section(truck, request) -> dict[str, Any]:
    if truck is None:
        return {
            'truck_id': None,
            'truck_code': None,
            'plate_number': None,
            'truck_status': None,
            'sourcing_mode': None,
        }
    return {
        'truck_id': str(truck.truck_id),
        'truck_code': truck.truck_code,
        'plate_number': truck.plate_number,
        'truck_status': truck.status,
        'sourcing_mode': truck.sourcing_mode,
    }


def _serialize_truck_type_section(truck_type, request) -> dict[str, Any]:
    if truck_type is None:
        return {
            'truck_type_id': None,
            'truck_type_code': None,
            **serialize_localized_label(request, None, None),
        }
    return {
        'truck_type_id': str(truck_type.truck_type_id),
        'truck_type_code': truck_type.truck_type_code,
        **serialize_localized_label(
            request,
            english_value=truck_type.english_label,
            arabic_value=truck_type.arabic_label,
        ),
    }


def _serialize_licence_section(driver, request) -> dict[str, Any]:
    if driver is None:
        return {
            'dl_number': None,
            'dl_expiry_date': None,
            'dl_status': None,
            'dl_image_url': None,
        }
    dl_status = getattr(driver, 'dl_status', None)
    if dl_status is not None and hasattr(dl_status, 'value'):
        dl_status_str = dl_status.value
    else:
        dl_status_str = str(dl_status) if dl_status is not None else None
    return {
        'dl_number': driver.dl_number or '',
        'dl_expiry_date': driver.dl_expiry_date,
        'dl_status': dl_status_str,
        'dl_image_url': safe_media_url(request, driver.dl_image),
    }


def _serialize_assignment_section(assignment, request) -> dict[str, Any]:
    if assignment is None:
        return {
            'assigned_from': None,
            'assignment_status': None,
        }
    status = getattr(assignment, 'assignment_status', None)
    return {
        'assigned_from': assignment.assigned_from,
        'assignment_status': status,
    }


class DriverProfileSerializer(LocalizedSerializerMixin, serializers.Serializer):
    """
    Read-only aggregate driver profile for mobile clients.

    Pass ``instance`` as a mapping with optional keys:
      - driver: DriverMaster | None
      - tenant_user: TenantUser | None
      - current_truck: TruckMaster | None
      - truck_type: TruckTypeMaster | None (defaults to current_truck.truck_type)
      - assignment: TruckDriverAssignmentHistory | None

    Localized display (``Accept-Language`` via ``serialize_localized_*``):
      - ``driver`` includes ``name`` (not ``english_name`` / ``arabic_name``).
      - ``truck_type`` includes ``label`` (not ``english_label`` / ``arabic_label``).

    Phase 1: ``profile_photo_url`` mirrors ``licence.dl_image_url`` (dl_image fallback).
    When a dedicated avatar field exists later, build its URL here without changing
    API consumers' key names.
    """

    def to_representation(self, instance: Any) -> dict[str, Any]:
        request = self.context.get('request')
        if not isinstance(instance, dict):
            instance = {}

        driver = instance.get('driver')
        tenant_user = instance.get('tenant_user')
        current_truck = instance.get('current_truck')
        truck_type = instance.get('truck_type')
        if truck_type is None and current_truck is not None:
            truck_type = getattr(current_truck, 'truck_type', None)
        assignment = instance.get('assignment')

        driver_block = _serialize_driver_section(driver, request)
        tenant_block = _serialize_tenant_user_section(tenant_user, request)
        truck_block = _serialize_truck_section(current_truck, request)
        truck_type_block = _serialize_truck_type_section(truck_type, request)
        licence_block = _serialize_licence_section(driver, request)
        assignment_block = _serialize_assignment_section(assignment, request)

        # Phase 1 avatar fallback = driving licence scan image (explicit contract).
        profile_photo_url = licence_block.get('dl_image_url')

        return {
            'driver': driver_block,
            'tenant_user': tenant_block,
            'current_truck': truck_block,
            'truck_type': truck_type_block,
            'licence': licence_block,
            'assignment': assignment_block,
            'profile_photo_url': profile_photo_url,
        }
