"""
mobile_api/helpers/driver_identity.py

Shared email / phone+extension identity resolution for driver auth flows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


def normalize_phone_digits(phone: str) -> str:
    return ''.join(ch for ch in (phone or '').strip() if ch.isdigit())


def normalize_extension(extension: str) -> str:
    ext = (extension or '').strip()
    if not ext:
        return ''
    if not ext.startswith('+'):
        ext = f'+{ext}'
    return ext


def extension_lookup_variants(extension: str) -> list[str]:
    """DB may store ``+966`` or ``966`` — match both."""
    ext = normalize_extension(extension)
    if not ext:
        return []
    variants = {ext}
    if ext.startswith('+'):
        variants.add(ext[1:])
    else:
        variants.add(f'+{ext}')
    return list(variants)


@dataclass(frozen=True)
class DriverAuthIdentity:
    """Normalized login / password-reset identity from API input."""

    email: str = ''
    phone: str = ''
    extension: str = ''

    @property
    def use_phone(self) -> bool:
        return bool(self.phone and self.extension)

    @property
    def email_normalized(self) -> str:
        return (self.email or '').strip().lower()


def validate_email_or_phone_identity_data(data: dict[str, Any]) -> DriverAuthIdentity:
    """
  Validate serializer ``data`` — same rules as ``DriverLoginSerializer``.

    Raises ``serializers.ValidationError`` on invalid combinations.
    """
    raw_email = data.get('email', '')
    if isinstance(raw_email, str):
        email = raw_email.strip().lower() if raw_email.strip() else ''
    else:
        email = ''

    phone = normalize_phone_digits(str(data.get('phone') or ''))
    extension = (
        normalize_extension(str(data.get('extension') or ''))
        if phone
        else str(data.get('extension') or '').strip()
    )

    if email and phone:
        raise serializers.ValidationError(
            _('Provide either email or phone+extension, not both.'),
        )
    if not email and not phone:
        raise serializers.ValidationError(
            _('Either email or phone is required.'),
        )
    if phone and not extension:
        raise serializers.ValidationError(
            _('extension is required when using phone login.'),
        )

    return DriverAuthIdentity(email=email, phone=phone, extension=extension)


def identity_from_validated(validated_data: dict[str, Any]) -> DriverAuthIdentity:
    """Build identity from already field-validated serializer output."""
    email = validated_data.get('email', '')
    if isinstance(email, str):
        email = email.strip().lower() if email.strip() else ''
    else:
        email = ''
    phone = normalize_phone_digits(str(validated_data.get('phone') or ''))
    extension = (
        normalize_extension(str(validated_data.get('extension') or ''))
        if phone
        else str(validated_data.get('extension') or '').strip()
    )
    return DriverAuthIdentity(email=email, phone=phone, extension=extension)


def get_driver_user_by_phone(
    phone: str,
    extension: str,
    tenant_schema: str,
) -> Any | None:
    """
    Find ``TenantUser`` by ``mobile_no`` + ``mobile_country_code``.

    Falls back to ``DriverMaster.mobile_number`` when the user row has no mobile.
    """
    from django_tenants.utils import schema_context

    num = normalize_phone_digits(phone)
    if not num:
        return None
    codes = extension_lookup_variants(extension)
    try:
        from tenant_workspace.models import DriverMaster, TenantUser

        with schema_context(tenant_schema):
            qs = TenantUser.all_objects.filter(mobile_no=num)
            if codes:
                tenant_user = qs.filter(mobile_country_code__in=codes).first()
            else:
                tenant_user = qs.first()
            if tenant_user is not None:
                return tenant_user

            driver = (
                DriverMaster.objects.filter(mobile_number=num)
                .select_related('user_account_id')
                .first()
            )
            if driver is None or not driver.user_account_id_id:
                return None
            return driver.user_account_id
    except Exception:
        return None


def resolve_canonical_email_for_identity(
    identity: DriverAuthIdentity,
    tenant_schema: str,
) -> str:
    """
    Canonical email for OTP storage and lookup.

    Phone identities resolve the linked ``TenantUser.email`` in-schema.
    """
    if identity.email_normalized:
        return identity.email_normalized
    if identity.use_phone and (tenant_schema or '').strip():
        user = get_driver_user_by_phone(
            identity.phone,
            identity.extension,
            tenant_schema.strip(),
        )
        if user is not None:
            return (getattr(user, 'email', '') or '').strip().lower()
    return ''
