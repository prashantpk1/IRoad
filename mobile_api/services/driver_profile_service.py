"""
mobile_api/services/driver_profile_service.py

Authenticated driver profile and change-password (OTP) business logic.

Views must not query the DB directly for these flows — call functions here.

OTP storage reuses ``DriverPasswordResetOTP`` (same lifecycle as forgot-password).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions
from django.db.models import F
from django.conf import settings as django_settings
from django.utils.translation import gettext as _
from django_tenants.utils import schema_context

from mobile_api.helpers.auth import blacklist_token_jti
from mobile_api.models import DriverPasswordResetOTP
from mobile_api.serializers.driver_profile import (
    PROFILE_PHOTO_ALLOWED_EXTENSIONS,
    PROFILE_PHOTO_MAX_SIZE_BYTES,
    safe_media_url,
)
from mobile_api.services.driver_auth_service import (
    generate_otp,
    get_driver_master_by_user,
    send_driver_reset_otp_email,
)

from tenant_workspace.models import DriverMaster, TenantUser

logger = logging.getLogger('mobile_api')


def _get_tenant_user_by_id(user_id: str, tenant_schema: str):
    try:
        with schema_context(tenant_schema):
            return TenantUser.all_objects.filter(pk=user_id).first()
    except Exception as exc:
        logger.error('get_tenant_user_by_id error: %s', exc)
        return None


def _jwt_email_matches_user(tenant_user, jwt_email: str | None) -> bool:
    if not jwt_email:
        return True
    return (
        (tenant_user.email or '').strip().lower()
        == str(jwt_email).strip().lower()
    )


def _resolve_driver_context(
    *,
    user_id: str,
    tenant_schema: str,
    jwt_email: str | None = None,
) -> dict[str, Any]:
    """
    Load TenantUser + DriverMaster for the authenticated mobile identity.

    Returns:
        {'success': True, 'tenant_user': u, 'driver': d}
        {'success': False, 'error': lazy_str}
    """
    if not tenant_schema or not user_id:
        return {'success': False, 'error': _('mobile.auth.unauthorized')}

    tenant_user = _get_tenant_user_by_id(user_id, tenant_schema)
    if tenant_user is None:
        return {'success': False, 'error': _('mobile.auth.unauthorized')}

    if getattr(tenant_user, 'is_deleted', False):
        return {'success': False, 'error': _('mobile.auth.account_deleted')}

    if not _jwt_email_matches_user(tenant_user, jwt_email):
        return {'success': False, 'error': _('mobile.auth.unauthorized')}

    user_status = getattr(tenant_user, 'status', None)
    if user_status and str(user_status).lower() not in ('active', 'Active'):
        return {'success': False, 'error': _('mobile.auth.account_inactive')}

    driver = get_driver_master_by_user(tenant_user, tenant_schema)
    if driver is None:
        return {'success': False, 'error': _('mobile.auth.not_a_driver')}
    if str(driver.driver_status) != 'Active':
        return {'success': False, 'error': _('mobile.auth.driver_inactive')}

    return {
        'success': True,
        'tenant_user': tenant_user,
        'driver': driver,
    }


def _assignment_history_rows(driver, limit: int = 15) -> list[dict[str, Any]]:
    """Recent truck assignment rows for operational summary (tenant schema)."""
    from tenant_workspace.models import TruckDriverAssignmentHistory

    rows: list[dict[str, Any]] = []
    qs = (
        TruckDriverAssignmentHistory.objects.filter(driver=driver)
        .select_related('truck', 'truck__truck_type')
        .order_by('-assigned_from', '-created_at')[:limit]
    )
    for a in qs:
        t = a.truck
        rows.append(
            {
                'assignment_id': str(a.assignment_id),
                'truck_id': str(t.truck_id) if t else None,
                'truck_code': getattr(t, 'truck_code', None),
                'plate_number': getattr(t, 'plate_number', None),
                'assigned_from': a.assigned_from,
                'assigned_to': a.assigned_to,
                'assignment_status': a.assignment_status,
            }
        )
    return rows


def _build_organization_summary(
    *,
    request,
    tenant_schema: str,
    org_profile,
) -> dict[str, Any]:
    from iroad_tenants.models import TenantRegistry
    from mobile_api.serializers.driver_organization_profile import (
        DriverOrganizationProfileSerializer,
    )

    flat: dict[str, Any] = {}
    if org_profile is not None:
        flat = DriverOrganizationProfileSerializer(
            instance=org_profile,
            context={'request': request},
        ).data
    reg = None
    try:
        reg = (
            TenantRegistry.objects.select_related('tenant_profile')
            .filter(schema_name=tenant_schema)
            .first()
        )
    except Exception as exc:
        logger.warning('organization registry lookup failed: %s', exc)
    tp = getattr(reg, 'tenant_profile', None) if reg else None
    flat['tenant_id'] = str(reg.tenant_profile_id) if reg else ''
    flat['schema_name'] = tenant_schema or ''
    flat['company_name'] = (tp.company_name or '') if tp else ''
    return flat


def _build_settings_dict(*, request, org_profile) -> dict[str, Any]:
    from mobile_api.helpers.i18n import SUPPORTED_LANGUAGES, get_request_language

    tz = getattr(django_settings, 'TIME_ZONE', 'UTC')
    sys_lang = 'en'
    date_fmt = 'DD/MM/YYYY'
    num_fmt = '1,234.56'
    neg_fmt = '-100'
    if org_profile is not None:
        sys_lang = getattr(org_profile, 'system_language', None) or 'en'
        tz = getattr(org_profile, 'timezone', None) or tz
        date_fmt = getattr(org_profile, 'date_format', None) or date_fmt
        num_fmt = getattr(org_profile, 'number_format', None) or num_fmt
        neg_fmt = getattr(org_profile, 'negative_format', None) or neg_fmt

    return {
        'request_language': get_request_language(request),
        'supported_languages': sorted(SUPPORTED_LANGUAGES),
        'timezone': tz,
        'system_language': sys_lang,
        'date_format': date_fmt,
        'number_format': num_fmt,
        'negative_format': neg_fmt,
    }


def _build_operational_summary(
    *,
    driver,
    assignment,
    truck,
    tenant_schema: str,
) -> dict[str, Any]:
    from tenant_workspace.models import DriverSettings

    driver_assignment_required = False
    try:
        driver_assignment_required = bool(
            DriverSettings.get_or_create_singleton().driver_assignment_required
        )
    except Exception as exc:
        logger.debug('DriverSettings singleton read failed: %s', exc)

    current = {
        'assignment_id': str(assignment.assignment_id) if assignment else None,
        'truck_id': str(truck.truck_id) if truck else None,
        'truck_code': getattr(truck, 'truck_code', None),
        'plate_number': getattr(truck, 'plate_number', None),
        'assigned_from': assignment.assigned_from if assignment else None,
        'assigned_to': assignment.assigned_to if assignment else None,
        'assignment_status': assignment.assignment_status if assignment else None,
    }
    return {
        'tenant_schema': tenant_schema,
        'driver_assignment_required': driver_assignment_required,
        'current_assignment': current,
        'assignment_history': _assignment_history_rows(driver),
    }


def _build_contact_dict(*, tenant_user, driver) -> dict[str, Any]:
    uid = str(tenant_user.pk) if tenant_user else ''
    return {
        'user_id': uid or None,
        'email': getattr(tenant_user, 'email', None),
        'full_name': getattr(tenant_user, 'full_name', None),
        'username': getattr(tenant_user, 'username', None),
        'mobile_country_code': getattr(tenant_user, 'mobile_country_code', None)
        or '',
        'mobile_no': getattr(tenant_user, 'mobile_no', None) or '',
        'driver_mobile_number': getattr(driver, 'mobile_number', None),
        'driver_whatsapp_number': getattr(driver, 'whatsapp_number', None) or '',
    }


def _build_permissions_dict(
    *,
    tenant_user,
    driver,
    request=None,
) -> dict[str, Any]:
    core = {
        'role_name': getattr(tenant_user, 'role_name', '') or '',
        'user_status': getattr(tenant_user, 'status', ''),
        'driver_status': getattr(driver, 'driver_status', ''),
    }
    if request is not None:
        from mobile_api.serializers.rbac import serialize_mobile_rbac_permissions

        snap = serialize_mobile_rbac_permissions(request)
        if snap:
            core['rbac'] = snap
    return core


def _otp_email_key(tenant_user) -> str:
    return (tenant_user.email or '').strip().lower()


def _phone_for_sms(tenant_user, driver) -> str | None:
    """
    Build a single recipient string for SMS gateways.

    Prefer TenantUser mobile_country_code + mobile_no; fall back to driver mobile.
    """
    code = (getattr(tenant_user, 'mobile_country_code', None) or '').strip()
    num = (getattr(tenant_user, 'mobile_no', None) or '').strip()
    combined = f'{code}{num}'.strip()
    if combined:
        return combined
    dm = (getattr(driver, 'mobile_number', None) or '').strip()
    if dm and re.match(r'^\d+$', dm):
        return dm
    return None


def _send_change_password_otp_sms(phone: str, otp_code: str) -> bool:
    try:
        from superadmin.communication_helpers import send_transactional_sms
        from mobile_api.models import OTP_EXPIRY_MINUTES

        body = (
            f'Your iRoad verification code is {otp_code}. '
            f'It expires in {OTP_EXPIRY_MINUTES} minutes.'
        )
        return bool(
            send_transactional_sms(
                phone,
                body,
                trigger_source='Mobile: change password OTP',
            )
        )
    except Exception as exc:
        logger.error('change password SMS send failed: %s', exc)
        return False


def driver_request_change_password_otp(
    *,
    user_id: str,
    tenant_schema: str,
    send_via: str,
    jwt_payload: dict | None = None,
) -> dict[str, Any]:
    """
    Authenticated driver requests OTP to change password.

    Identity comes only from JWT (user_id + tenant_schema + email in payload).
    ``send_via`` is ``email`` or ``mobile`` (SMS uses tenant user phone when set).

    Reuses ``DriverPasswordResetOTP.create_for_email`` (invalidates prior PENDING;
    new row has attempts=0 and fresh expiry).

    Returns:
        {'success': True}
        {'success': False, 'error': ...}
    """
    jwt_email = (jwt_payload or {}).get('email')
    ctx = _resolve_driver_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        jwt_email=jwt_email,
    )
    if not ctx['success']:
        return {'success': False, 'error': ctx['error']}

    tenant_user = ctx['tenant_user']
    driver = ctx['driver']
    email_key = _otp_email_key(tenant_user)

    otp_code = generate_otp()
    DriverPasswordResetOTP.create_for_email(
        email=email_key,
        tenant_schema=tenant_schema,
        otp_code=otp_code,
        expire_verified=True,
    )

    dispatch_ok = False
    if send_via == 'email':
        dispatch_ok = send_driver_reset_otp_email(
            recipient_email=tenant_user.email,
            otp_code=otp_code,
            tenant_schema=tenant_schema,
            user_name=getattr(tenant_user, 'full_name', '') or email_key,
        )
        if not dispatch_ok:
            logger.warning(
                'Change-password OTP email dispatch failed schema=%s user_id=%s',
                tenant_schema,
                user_id,
            )
    elif send_via == 'mobile':
        phone = _phone_for_sms(tenant_user, driver)
        if not phone:
            return {
                'success': False,
                'error': _('mobile.profile.phone_missing_for_sms'),
            }
        dispatch_ok = _send_change_password_otp_sms(phone, otp_code)
        if not dispatch_ok:
            logger.warning(
                'Change-password OTP SMS dispatch failed schema=%s user_id=%s',
                tenant_schema,
                user_id,
            )
    else:
        return {'success': False, 'error': _('mobile.profile.send_via_invalid')}

    logger.info(
        'Change-password OTP issued schema=%s user_id=%s channel=%s',
        tenant_schema,
        user_id,
        send_via,
    )
    return {'success': True}


def driver_verify_change_password_otp(
    *,
    user_id: str,
    tenant_schema: str,
    otp_code: str,
    jwt_payload: dict | None = None,
) -> dict[str, Any]:
    """
    Verify change-password OTP for the authenticated driver (JWT-bound email).

    Returns:
        {'success': True, 'attempts_remaining': 5}
        {'success': False, 'error': ..., 'attempts_remaining': n?}
    """
    jwt_email = (jwt_payload or {}).get('email')
    ctx = _resolve_driver_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        jwt_email=jwt_email,
    )
    if not ctx['success']:
        return {'success': False, 'error': ctx['error']}

    tenant_user = ctx['tenant_user']
    email_key = _otp_email_key(tenant_user)

    otp_record = DriverPasswordResetOTP.get_valid_otp(
        email=email_key,
        tenant_schema=tenant_schema,
    )
    if otp_record is None:
        return {
            'success': False,
            'error': _('mobile.auth.otp_not_found'),
            'attempts_remaining': 0,
            'verified': False,
        }

    if otp_record.is_expired:
        otp_record.status = DriverPasswordResetOTP.Status.EXPIRED
        with schema_context(tenant_schema):
            otp_record.save(update_fields=['status'])
        return {
            'success': False,
            'error': _('mobile.validation.otp_expired'),
            'attempts_remaining': 0,
            'verified': False,
        }

    if otp_record.attempts >= 5:
        return {
            'success': False,
            'error': _('mobile.auth.otp_max_attempts'),
            'attempts_remaining': 0,
            'verified': False,
        }

    if otp_record.otp_code != otp_code.strip():
        otp_record.attempts += 1
        with schema_context(tenant_schema):
            otp_record.save(update_fields=['attempts'])
        remaining = max(0, 5 - otp_record.attempts)
        return {
            'success': False,
            'error': _('mobile.validation.invalid_otp'),
            'attempts_remaining': remaining,
            'verified': False,
        }

    otp_record.status = DriverPasswordResetOTP.Status.VERIFIED
    otp_record.verified_at = timezone.now()
    with schema_context(tenant_schema):
        otp_record.save(update_fields=['status', 'verified_at'])

    return {
        'success': True,
        'attempts_remaining': max(0, 5 - otp_record.attempts),
        'verified': True,
    }


def driver_change_password(
    *,
    user_id: str,
    tenant_schema: str,
    current_password: str,
    new_password: str,
    otp_code: str,
    jwt_payload: dict | None = None,
    access_jti: str | None = None,
    access_exp_ts: int | None = None,
) -> dict[str, Any]:
    """
    Change password after OTP verification.

    - Verifies ``current_password`` against ``TenantUser.password_hash``.
    - Consumes latest ``VERIFIED`` OTP matching ``otp_code`` (marks ``USED``).
    - Blacklists the current access token JTI when provided (session invalidation).

    Does not log passwords or OTP codes.
    """
    jwt_email = (jwt_payload or {}).get('email')
    ctx = _resolve_driver_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        jwt_email=jwt_email,
    )
    if not ctx['success']:
        return {'success': False, 'error': ctx['error']}

    tenant_user = ctx['tenant_user']
    email_key = _otp_email_key(tenant_user)

    if not check_password(current_password, tenant_user.password_hash):
        return {
            'success': False,
            'error': _('mobile.auth.current_password_invalid'),
        }

    otp_record = DriverPasswordResetOTP.get_verified_otp(
        email=email_key,
        tenant_schema=tenant_schema,
    )
    if otp_record is None:
        return {
            'success': False,
            'error': _('mobile.auth.change_password_requires_verified_otp'),
        }

    if otp_record.otp_code != otp_code.strip():
        return {
            'success': False,
            'error': _('mobile.validation.invalid_otp'),
        }

    if otp_record.is_expired:
        otp_record.status = DriverPasswordResetOTP.Status.EXPIRED
        with schema_context(tenant_schema):
            otp_record.save(update_fields=['status'])
        return {
            'success': False,
            'error': _('mobile.validation.otp_expired'),
        }

    if otp_record.status == DriverPasswordResetOTP.Status.USED:
        return {
            'success': False,
            'error': _('mobile.auth.change_password_requires_verified_otp'),
        }

    if check_password(new_password, tenant_user.password_hash):
        return {
            'success': False,
            'error': _('mobile.profile.new_password_same_as_current'),
        }

    new_hash = make_password(new_password)
    with schema_context(tenant_schema):
        TenantUser.all_objects.filter(pk=tenant_user.pk).update(
            password_hash=new_hash,
            mobile_token_version=F('mobile_token_version') + 1,
        )
        DriverPasswordResetOTP.objects.filter(pk=otp_record.pk).update(
            status=DriverPasswordResetOTP.Status.USED,
            used_at=timezone.now(),
        )
        DriverPasswordResetOTP.objects.filter(
            email=email_key,
            tenant_schema=tenant_schema,
            status=DriverPasswordResetOTP.Status.PENDING,
        ).update(status=DriverPasswordResetOTP.Status.EXPIRED)

    if access_jti:
        try:
            blacklist_token_jti(jti=access_jti, exp_ts=access_exp_ts)
            from superadmin.redis_helpers import revoke_tenant_session_by_jti

            revoke_tenant_session_by_jti(access_jti)
        except Exception as exc:
            logger.error('post password-change token revoke error: %s', exc)

    logger.info(
        'mobile.session event=driver_password_changed schema=%s user_id=%s',
        tenant_schema,
        user_id,
    )
    return {'success': True}


def get_driver_profile(
    *,
    user_id: str,
    tenant_schema: str,
    jwt_payload: dict | None = None,
    request=None,
) -> dict[str, Any]:
    """
    Build profile payload for mobile clients (serialized dict).

    Current truck assignment rule:
      ``TruckDriverAssignmentHistory`` rows with ``assigned_to IS NULL``,
      latest by ``assigned_from`` then ``created_at``.

    Includes organization summary, permissions, locale/settings from
    ``OrganizationProfile``, operational assignment history, and merged contact.

    All ORM access and ``DriverProfileSerializer`` rendering run inside
    ``schema_context(tenant_schema)`` so FKs resolve in the correct tenant.

    Returns:
        {'success': True, 'profile': <nested dict>}
        {'success': False, 'error': ...}
    """
    from tenant_workspace.models import (
        OrganizationProfile,
        TruckDriverAssignmentHistory,
    )
    from mobile_api.serializers.driver_profile import DriverProfileSerializer

    jwt_email = (jwt_payload or {}).get('email')
    if not tenant_schema or not user_id:
        return {'success': False, 'error': _('mobile.auth.unauthorized')}

    with schema_context(tenant_schema):
        tenant_user = TenantUser.all_objects.filter(pk=user_id).first()
        if tenant_user is None:
            return {'success': False, 'error': _('mobile.auth.unauthorized')}
        if getattr(tenant_user, 'is_deleted', False):
            return {'success': False, 'error': _('mobile.auth.account_deleted')}
        if not _jwt_email_matches_user(tenant_user, jwt_email):
            return {'success': False, 'error': _('mobile.auth.unauthorized')}
        user_status = getattr(tenant_user, 'status', None)
        if user_status and str(user_status).lower() not in (
            'active',
            'Active',
        ):
            return {'success': False, 'error': _('mobile.auth.account_inactive')}

        driver = (
            DriverMaster.objects.select_related('nationality_country')
            .filter(user_account_id=tenant_user.pk)
            .first()
        )
        if driver is None:
            return {'success': False, 'error': _('mobile.auth.not_a_driver')}
        if str(driver.driver_status) != 'Active':
            return {'success': False, 'error': _('mobile.auth.driver_inactive')}

        assignment = (
            TruckDriverAssignmentHistory.objects.filter(
                driver=driver,
                assigned_to__isnull=True,
            )
            .select_related('truck', 'truck__truck_type')
            .order_by('-assigned_from', '-created_at')
            .first()
        )
        truck = assignment.truck if assignment else None
        truck_type = truck.truck_type if truck else None

        org_profile = (
            OrganizationProfile.objects.order_by('-updated_at', '-created_at').first()
        )

        profile_ctx = {
            'driver': driver,
            'tenant_user': tenant_user,
            'current_truck': truck,
            'truck_type': truck_type,
            'assignment': assignment,
            'organization': _build_organization_summary(
                request=request,
                tenant_schema=tenant_schema,
                org_profile=org_profile,
            ),
            'permissions': _build_permissions_dict(
                tenant_user=tenant_user,
                driver=driver,
                request=request,
            ),
            'settings': _build_settings_dict(
                request=request,
                org_profile=org_profile,
            ),
            'operational': _build_operational_summary(
                driver=driver,
                assignment=assignment,
                truck=truck,
                tenant_schema=tenant_schema,
            ),
            'contact': _build_contact_dict(
                tenant_user=tenant_user,
                driver=driver,
            ),
        }
        profile_data = DriverProfileSerializer(
            instance=profile_ctx,
            context={'request': request},
        ).data

    return {'success': True, 'profile': profile_data}


def update_driver_profile(
    *,
    user_id: str,
    tenant_schema: str,
    updates: dict[str, Any],
    jwt_payload: dict | None = None,
    request=None,
) -> dict[str, Any]:
    """
    Apply validated partial updates to ``TenantUser`` and ``DriverMaster``.

    Only fields present in ``updates`` are written. Re-reads profile on success.
    """
    jwt_email = (jwt_payload or {}).get('email')
    ctx = _resolve_driver_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        jwt_email=jwt_email,
    )
    if not ctx['success']:
        return {'success': False, 'error': ctx['error']}

    tenant_user = ctx['tenant_user']
    driver = ctx['driver']

    with schema_context(tenant_schema):
        tu = TenantUser.all_objects.filter(pk=tenant_user.pk).first()
        dr = DriverMaster.objects.filter(pk=driver.pk).first()
        if tu is None or dr is None:
            return {'success': False, 'error': _('mobile.auth.unauthorized')}

        tu_fields: list[str] = []
        dr_fields: list[str] = []

        if 'full_name' in updates:
            tu.full_name = str(updates['full_name']).strip()[:200]
            tu_fields.append('full_name')
        if 'mobile_country_code' in updates:
            tu.mobile_country_code = str(updates['mobile_country_code'] or '')[:8]
            tu_fields.append('mobile_country_code')
        if 'mobile_no' in updates:
            tu.mobile_no = str(updates['mobile_no'] or '')[:30]
            tu_fields.append('mobile_no')

        if 'english_name' in updates:
            dr.english_name = str(updates['english_name'] or '')[:200]
            dr_fields.append('english_name')
        if 'arabic_name' in updates:
            dr.arabic_name = str(updates['arabic_name']).strip()[:200]
            dr_fields.append('arabic_name')
        if 'mobile_number' in updates:
            dr.mobile_number = str(updates['mobile_number']).strip()[:30]
            dr_fields.append('mobile_number')
        if 'whatsapp_number' in updates:
            dr.whatsapp_number = str(updates['whatsapp_number'] or '').strip()[:30]
            dr_fields.append('whatsapp_number')
        if 'whatsapp_same_as_mobile' in updates:
            dr.whatsapp_same_as_mobile = bool(updates['whatsapp_same_as_mobile'])
            dr_fields.append('whatsapp_same_as_mobile')

        if dr.whatsapp_same_as_mobile:
            dr.whatsapp_number = (dr.mobile_number or '').strip()[:30]
            if 'whatsapp_number' not in dr_fields:
                dr_fields.append('whatsapp_number')

        if tu_fields:
            tu_fields.append('updated_at')
            tu.save(update_fields=tu_fields)
        if dr_fields:
            dr_fields.append('updated_at')
            dr.save(update_fields=dr_fields)

    return get_driver_profile(
        user_id=user_id,
        tenant_schema=tenant_schema,
        jwt_payload=jwt_payload,
        request=request,
    )
    """Raise ValidationError if upload violates Phase-1 image rules."""
    name = getattr(uploaded_file, 'name', '') or ''
    ext = os.path.splitext(name)[1].lower()
    if ext not in PROFILE_PHOTO_ALLOWED_EXTENSIONS:
        raise ValidationError(_('mobile.validation.invalid_image'))
    size = getattr(uploaded_file, 'size', None)
    if size is not None and size > PROFILE_PHOTO_MAX_SIZE_BYTES:
        size_mb = round(size / 1024 / 1024, 1)
        max_mb = PROFILE_PHOTO_MAX_SIZE_BYTES // (1024 * 1024)
        raise ValidationError(
            str(_('mobile.validation.image_too_large'))
            % {'max_mb': max_mb, 'size_mb': size_mb}
        )
    content_type = getattr(uploaded_file, 'content_type', '') or ''
    if content_type and not content_type.startswith('image/'):
        raise ValidationError(_('mobile.validation.invalid_image'))
    try:
        if hasattr(uploaded_file, 'seek'):
            uploaded_file.seek(0)
        get_image_dimensions(uploaded_file)
    except Exception:
        raise ValidationError(_('mobile.validation.invalid_image'))
    finally:
        if hasattr(uploaded_file, 'seek'):
            try:
                uploaded_file.seek(0)
            except Exception:
                pass


def update_driver_profile_photo(
    *,
    user_id: str,
    tenant_schema: str,
    uploaded_file,
    jwt_payload: dict | None = None,
    request=None,
) -> dict[str, Any]:
    """
    Phase 1: persist profile photo on ``DriverMaster.dl_image``.

    Later: swap to a dedicated ``profile_photo`` field with minimal changes here.

    Deletes the previous stored file when replacing (Django storage).
    """
    jwt_email = (jwt_payload or {}).get('email')
    ctx = _resolve_driver_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        jwt_email=jwt_email,
    )
    if not ctx['success']:
        return {'success': False, 'error': ctx['error']}

    driver = ctx['driver']

    try:
        _validate_profile_photo_upload(uploaded_file)
    except ValidationError as exc:
        # Single-message API style
        msg = exc.messages[0] if exc.messages else _('mobile.validation.failed')
        return {'success': False, 'error': msg}

    with schema_context(tenant_schema):
        from tenant_workspace.models import DriverMaster

        driver_db = DriverMaster.objects.filter(pk=driver.pk).first()
        if driver_db is None:
            return {'success': False, 'error': _('mobile.auth.not_a_driver')}

        if driver_db.dl_image:
            try:
                driver_db.dl_image.delete(save=False)
            except Exception as exc:
                logger.warning('Old dl_image delete failed pk=%s: %s', driver_db.pk, exc)

        driver_db.dl_image = uploaded_file
        driver_db.save(update_fields=['dl_image', 'updated_at'])

        driver_db.refresh_from_db()

        photo_url = safe_media_url(request, driver_db.dl_image)

    return {
        'success': True,
        'profile_photo_url': photo_url,
    }
