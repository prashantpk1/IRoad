"""
mobile_api/services/driver_auth_service.py

Business logic for Driver Authentication.
All database operations and auth logic here.
Views call this service — no direct DB in views.

Multi-tenant aware:
  All DB queries run inside the correct tenant schema.
  Schema is already set by TenantMainMiddleware or
  X-Tenant-ID header handling before this runs.
"""
import secrets
import logging
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from django.utils.translation import gettext as _
from django_tenants.utils import schema_context

from mobile_api.helpers.auth import generate_token_pair
from mobile_api.serializers.localized import serialize_localized_name
from mobile_api.models import DriverPasswordResetOTP

logger = logging.getLogger('mobile_api')


# ── OTP Generation ────────────────────────────────────────────────

def generate_otp() -> str:
    """Generate a cryptographically secure 6-digit OTP."""
    return str(secrets.randbelow(900000) + 100000)


# ── Driver Lookup ─────────────────────────────────────────────────

def get_driver_user_by_email(email: str, tenant_schema: str):
    """
    Find TenantUser by email.
    Returns TenantUser instance or None.

    IMPORTANT: This runs in the current tenant schema context.
    The schema must be set before calling this.
    """
    try:
        from tenant_workspace.models import TenantUser
        with schema_context(tenant_schema):
            return TenantUser.all_objects.filter(
                email__iexact=email.strip(),
            ).first()
    except Exception as e:
        logger.error('get_driver_user_by_email error: %s', e)
        return None


def get_driver_master_by_user(tenant_user, tenant_schema: str):
    """
    Get DriverMaster linked to a TenantUser.
    Returns DriverMaster or None.
    """
    try:
        from tenant_workspace.models import DriverMaster
        with schema_context(tenant_schema):
            return DriverMaster.objects.filter(
                user_account_id=tenant_user.pk,
            ).select_related().first()
    except Exception as e:
        logger.error('get_driver_master_by_user error: %s', e)
        return None


def resolve_tenant_schema_for_login(email: str, password: str) -> str | None:
    """
    Auto-detect tenant schema from login credentials.
    Returns schema name when a matching user+password is found.
    """
    try:
        from iroad_tenants.models import TenantRegistry
        from tenant_workspace.models import TenantUser

        registries = TenantRegistry.objects.select_related(
            'tenant_profile'
        ).all()
        normalized_email = email.strip().lower()

        for reg in registries:
            try:
                profile = getattr(reg, 'tenant_profile', None)
                if profile and getattr(profile, 'account_status', None) != 'Active':
                    continue
                with schema_context(reg.schema_name):
                    tenant_user = TenantUser.objects.filter(
                        email__iexact=normalized_email,
                    ).first()
                    if tenant_user and check_password(password, tenant_user.password_hash):
                        return reg.schema_name
            except Exception:
                # Ignore invalid tenant schema states and continue.
                continue
    except Exception as e:
        logger.error('resolve_tenant_schema_for_login error: %s', e)
    return None


def resolve_tenant_schema_for_email(email: str) -> str | None:
    """
    Auto-detect tenant schema from email only.
    Returns the first active tenant containing this user.
    """
    try:
        from iroad_tenants.models import TenantRegistry
        from tenant_workspace.models import TenantUser

        registries = TenantRegistry.objects.select_related(
            'tenant_profile'
        ).all()
        normalized_email = email.strip().lower()

        for reg in registries:
            try:
                profile = getattr(reg, 'tenant_profile', None)
                if profile and getattr(profile, 'account_status', None) != 'Active':
                    continue
                with schema_context(reg.schema_name):
                    exists = TenantUser.objects.filter(
                        email__iexact=normalized_email,
                    ).exists()
                    if exists:
                        return reg.schema_name
            except Exception:
                continue
    except Exception as e:
        logger.error('resolve_tenant_schema_for_email error: %s', e)
    return None


def resolve_tenant_schema_for_otp(
    email: str,
    otp_code: str,
    otp_status: str,
) -> str | None:
    """
    Find tenant schema by matching OTP record across active tenant schemas.
    """
    try:
        from iroad_tenants.models import TenantRegistry

        registries = TenantRegistry.objects.select_related(
            'tenant_profile'
        ).all()
        normalized_email = email.strip().lower()
        normalized_otp = otp_code.strip()

        for reg in registries:
            try:
                profile = getattr(reg, 'tenant_profile', None)
                if profile and getattr(profile, 'account_status', None) != 'Active':
                    continue
                with schema_context(reg.schema_name):
                    exists = DriverPasswordResetOTP.objects.filter(
                        email=normalized_email,
                        otp_code=normalized_otp,
                        status=otp_status,
                    ).exists()
                    if exists:
                        return reg.schema_name
            except Exception:
                continue
    except Exception as e:
        logger.error('resolve_tenant_schema_for_otp error: %s', e)
    return None


def build_token_claims(tenant_schema: str, tenant_user, driver) -> dict:
    """Build essential identity claims for mobile JWT payload."""
    claims = {
        'email': tenant_user.email,
        'username': tenant_user.username,
        'full_name': tenant_user.full_name,
        'role_name': tenant_user.role_name,
        'driver_id': str(driver.driver_id),
        'driver_code': driver.driver_code,
    }
    try:
        from iroad_tenants.models import TenantRegistry
        tenant_registry = TenantRegistry.objects.filter(
            schema_name=tenant_schema,
        ).first()
        if tenant_registry:
            claims['company_id'] = str(tenant_registry.tenant_profile_id)
            claims['tenant_id'] = str(tenant_registry.tenant_profile_id)
    except Exception as e:
        logger.error('build_token_claims tenant lookup error: %s', e)
    return claims


def send_driver_reset_otp_email(
    *,
    recipient_email: str,
    otp_code: str,
    tenant_schema: str,
    user_name: str,
) -> bool:
    """
    Send OTP email for mobile forgot-password using web-style notification pipeline:
    1) named template
    2) event mapping dispatcher
    3) direct transactional fallback
    """
    context_dict = {
        'otp_code': otp_code,
        'otp': otp_code,
        'user_name': user_name or recipient_email,
    }
    try:
        from iroad_tenants.models import TenantRegistry
        tenant_registry = TenantRegistry.objects.select_related(
            'tenant_profile'
        ).filter(schema_name=tenant_schema).first()
        if tenant_registry and tenant_registry.tenant_profile:
            context_dict['company_name'] = (
                tenant_registry.tenant_profile.company_name or ''
            )
    except Exception:
        pass

    try:
        from superadmin.communication_helpers import (
            send_named_notification_email,
            dispatch_event_notification,
            send_transactional_email,
        )

        sent = send_named_notification_email(
            'MOBILE_FORGOT_PASSWORD_OTP',
            recipient_email=recipient_email,
            context_dict=context_dict,
            default_subject='Your iRoad Password Reset OTP',
            trigger_source='TemplateName: MOBILE_FORGOT_PASSWORD_OTP',
            force_django_smtp=True,
        )
        if sent:
            return True
        logger.warning(
            'Template MOBILE_FORGOT_PASSWORD_OTP not found/inactive for %s',
            recipient_email,
        )

        sent = dispatch_event_notification(
            'OTP_Requested',
            recipient_email=recipient_email,
            context_dict=context_dict,
            use_async_tasks=False,
        )
        if sent:
            return True

        sent = send_transactional_email(
            recipient_email,
            'Your iRoad OTP verification code',
            f'Your verification code is {otp_code}. It expires in 10 minutes.',
            (
                f'<p>Your verification code is <strong>{otp_code}</strong>.</p>'
                '<p>This code expires in 10 minutes.</p>'
            ),
            trigger_source='Direct: Mobile Forgot Password OTP',
        )
        if sent:
            return True
        logger.error(
            'Failed to send OTP via direct transactional fallback to %s',
            recipient_email,
        )
        return False
    except Exception as e:
        logger.error(
            'send_driver_reset_otp_email failed for %s schema=%s error=%s',
            recipient_email,
            tenant_schema,
            e,
        )
        return False


# ── API 1: Login ──────────────────────────────────────────────────

def driver_login(
    email: str,
    password: str,
    tenant_schema: str,
    *,
    request=None,
) -> dict:
    """
    Authenticate driver by email + password.

    Returns:
        {'success': True, 'tokens': {...}, 'driver': {...}}
        {'success': False, 'error': 'translation_key'}

    Checks:
    1. TenantUser exists with this email
    2. TenantUser is not soft-deleted
    3. Password matches password_hash
    4. TenantUser is active
    5. DriverMaster exists and is Active
    """
    # Step 0: Resolve tenant schema automatically when header is absent.
    if not tenant_schema:
        tenant_schema = resolve_tenant_schema_for_login(email, password) or ''
    if not tenant_schema:
        return {
            'success': False,
            'error': _('mobile.auth.invalid_credentials'),
        }

    # Step 1: Find user by email
    tenant_user = get_driver_user_by_email(email, tenant_schema)
    if tenant_user is None:
        return {
            'success': False,
            'error': _('mobile.auth.invalid_credentials'),
        }

    if getattr(tenant_user, 'is_deleted', False):
        return {
            'success': False,
            'error': _('mobile.auth.account_deleted'),
        }

    # Step 2: Verify password
    password_valid = check_password(
        password,
        tenant_user.password_hash,
    )
    if not password_valid:
        return {
            'success': False,
            'error': _('mobile.auth.invalid_credentials'),
        }

    # Step 3: Check TenantUser is active
    # Check status field on TenantUser
    user_status = getattr(tenant_user, 'status', None)
    if user_status and str(user_status).lower() not in (
        'active', 'Active'
    ):
        return {
            'success': False,
            'error': _('mobile.auth.account_inactive'),
        }

    # Step 4: Check DriverMaster exists and is Active
    driver = get_driver_master_by_user(tenant_user, tenant_schema)
    if driver is None:
        return {
            'success': False,
            'error': _('mobile.auth.not_a_driver'),
        }
    if str(driver.driver_status) != 'Active':
        return {
            'success': False,
            'error': _('mobile.auth.driver_inactive'),
        }

    # Step 5: Generate JWT token pair
    tokens = generate_token_pair(
        user_id=str(tenant_user.pk),
        tenant_schema=tenant_schema,
        extra_claims=build_token_claims(
            tenant_schema=tenant_schema,
            tenant_user=tenant_user,
            driver=driver,
        ),
    )

    # Step 6: Build driver profile for response
    driver_data = {
        'driver_id': str(driver.driver_id),
        'driver_code': driver.driver_code,
        **serialize_localized_name(
            request,
            english_value=driver.english_name or '',
            arabic_value=driver.arabic_name,
        ),
        'mobile_number': driver.mobile_number,
        'driver_status': driver.driver_status,
        'driver_type': str(driver.driver_type),
    }

    return {
        'success': True,
        'tokens': tokens,
        'driver': driver_data,
    }


# ── API 2: Forgot Password ────────────────────────────────────────

def driver_forgot_password(
    email: str,
    tenant_schema: str,
) -> dict:
    """
    Initiate password reset by sending OTP to email.

    Security note: Always return success even if email
    not found — prevents email enumeration attacks.

    Returns:
        {'success': True}
        {'success': False, 'error': 'key'}
    """
    if not tenant_schema:
        tenant_schema = resolve_tenant_schema_for_email(email) or ''
    if not tenant_schema:
        return {
            'success': False,
            'error': _('mobile.auth.user_not_found'),
            'email_dispatch_status': False,
        }

    tenant_user = get_driver_user_by_email(email, tenant_schema)

    if tenant_user is None:
        # DEBUG only: avoid INFO logs that embed raw email (enumeration / PII).
        logger.debug(
            'Forgot password: no tenant user for schema=%s',
            tenant_schema,
        )
        return {
            'success': False,
            'error': _('mobile.auth.user_not_found'),
            'email_dispatch_status': False,
        }

    if getattr(tenant_user, 'is_deleted', False):
        return {
            'success': False,
            'error': _('mobile.auth.user_not_found'),
            'email_dispatch_status': False,
        }

    # Check it is actually a driver
    driver = get_driver_master_by_user(tenant_user, tenant_schema)
    if driver is None:
        return {
            'success': False,
            'error': _('mobile.auth.not_a_driver'),
            'email_dispatch_status': False,
        }

    # Generate OTP
    otp_code = generate_otp()

    # Store OTP (invalidates previous pending OTPs)
    DriverPasswordResetOTP.create_for_email(
        email=email.lower().strip(),
        tenant_schema=tenant_schema,
        otp_code=otp_code,
    )

    # Never log raw OTP. Schema-only breadcrumb at INFO.
    logger.info(
        'Password reset OTP generated (schema=%s)',
        tenant_schema,
    )
    email_sent = send_driver_reset_otp_email(
        recipient_email=email.lower().strip(),
        otp_code=otp_code,
        tenant_schema=tenant_schema,
        user_name=getattr(tenant_user, 'full_name', '') or email,
    )
    if not email_sent:
        logger.warning(
            'Password reset OTP email dispatch failed for %s (schema=%s)',
            email,
            tenant_schema,
        )

    return {'success': True, 'email_dispatch_status': bool(email_sent)}


# ── API 3: Verify OTP ─────────────────────────────────────────────

def driver_verify_otp(
    email: str,
    otp_code: str,
    tenant_schema: str,
) -> dict:
    """
    Verify OTP for password reset.

    Returns:
        {'success': True}  — OTP valid, marked as Verified
        {'success': False, 'error': 'key'}
    """
    if not tenant_schema:
        tenant_schema = resolve_tenant_schema_for_otp(
            email=email,
            otp_code=otp_code,
            otp_status=DriverPasswordResetOTP.Status.PENDING,
        ) or ''
    if not tenant_schema:
        return {
            'success': False,
            'error': _('mobile.auth.otp_not_found'),
        }

    otp_record = DriverPasswordResetOTP.get_valid_otp(
        email=email.lower().strip(),
        tenant_schema=tenant_schema,
    )

    if otp_record is None:
        return {
            'success': False,
            'error': _('mobile.auth.otp_not_found'),
        }

    # Check expiry
    if otp_record.is_expired:
        otp_record.status = DriverPasswordResetOTP.Status.EXPIRED
        with schema_context(tenant_schema):
            otp_record.save(update_fields=['status'])
        return {
            'success': False,
            'error': _('mobile.auth.otp_expired'),
        }

    # Check max attempts
    if otp_record.attempts >= 5:
        return {
            'success': False,
            'error': _('mobile.auth.otp_max_attempts'),
        }

    # Check OTP code
    if otp_record.otp_code != otp_code.strip():
        otp_record.attempts += 1
        with schema_context(tenant_schema):
            otp_record.save(update_fields=['attempts'])
        remaining = 5 - otp_record.attempts
        return {
            'success': False,
            'error': _('mobile.auth.otp_wrong'),
            'attempts_remaining': remaining,
        }

    # OTP correct — mark as verified
    otp_record.status = DriverPasswordResetOTP.Status.VERIFIED
    otp_record.verified_at = timezone.now()
    with schema_context(tenant_schema):
        otp_record.save(update_fields=['status', 'verified_at'])

    return {'success': True}


# ── API 4: Reset Password ─────────────────────────────────────────

def driver_reset_password(
    email: str,
    otp_code: str,
    new_password: str,
    tenant_schema: str,
) -> dict:
    """
    Reset password after OTP verification.

    Steps:
    1. Check verified OTP exists for email+schema
    2. Verify OTP code matches
    3. Find TenantUser
    4. Update password_hash
    5. Mark OTP as used
    6. Invalidate any other pending OTPs

    Returns:
        {'success': True}
        {'success': False, 'error': 'key'}
    """
    if not tenant_schema:
        tenant_schema = resolve_tenant_schema_for_otp(
            email=email,
            otp_code=otp_code,
            otp_status=DriverPasswordResetOTP.Status.VERIFIED,
        ) or ''
    if not tenant_schema:
        return {
            'success': False,
            'error': _('mobile.auth.otp_not_verified'),
        }

    # Step 1: Get verified OTP
    otp_record = DriverPasswordResetOTP.get_verified_otp(
        email=email.lower().strip(),
        tenant_schema=tenant_schema,
    )

    if otp_record is None:
        return {
            'success': False,
            'error': _('mobile.auth.otp_not_verified'),
        }

    # Step 2: Verify OTP code matches
    if otp_record.otp_code != otp_code.strip():
        return {
            'success': False,
            'error': _('mobile.auth.otp_wrong'),
        }

    # Step 3: Check expiry
    if otp_record.is_expired:
        otp_record.status = DriverPasswordResetOTP.Status.EXPIRED
        with schema_context(tenant_schema):
            otp_record.save(update_fields=['status'])
        return {
            'success': False,
            'error': _('mobile.auth.otp_expired'),
        }

    # Step 4: Find TenantUser
    tenant_user = get_driver_user_by_email(email, tenant_schema)
    if tenant_user is None:
        return {
            'success': False,
            'error': _('mobile.auth.user_not_found'),
        }

    if getattr(tenant_user, 'is_deleted', False):
        return {
            'success': False,
            'error': _('mobile.auth.account_deleted'),
        }

    # Step 5: Update password hash
    tenant_user.password_hash = make_password(new_password)
    with schema_context(tenant_schema):
        tenant_user.save(update_fields=['password_hash'])

    # Step 6: Mark OTP as used
    otp_record.status = DriverPasswordResetOTP.Status.USED
    otp_record.used_at = timezone.now()
    with schema_context(tenant_schema):
        otp_record.save(update_fields=['status', 'used_at'])

    # Step 7: Invalidate any remaining pending OTPs
    with schema_context(tenant_schema):
        DriverPasswordResetOTP.objects.filter(
            email=email.lower().strip(),
            tenant_schema=tenant_schema,
            status=DriverPasswordResetOTP.Status.PENDING,
        ).update(status=DriverPasswordResetOTP.Status.EXPIRED)

    logger.info(
        'Password reset successful (schema=%s)',
        tenant_schema,
    )

    return {'success': True}


def _tenant_schema_from_driver_request(request) -> str:
    """Resolve tenant schema from ``request.tenant`` or verified Bearer access token."""
    tenant = getattr(request, 'tenant', None)
    schema = (getattr(tenant, 'schema_name', None) or '').strip()
    if schema:
        return schema
    try:
        from mobile_api.helpers.auth import (
            TOKEN_TYPE_ACCESS,
            get_token_from_request,
            verify_token,
        )

        token = get_token_from_request(request)
        if not token:
            return ''
        payload = verify_token(token, expected_type=TOKEN_TYPE_ACCESS)
        if not payload:
            return ''
        return str(payload.get('tenant_schema') or '').strip()
    except Exception:
        return ''


def _access_token_blacklist_entries_for_user(request, user_id) -> list | None:
    """
    Build ``mobile_tokens_to_blacklist`` entries for ``TenantUser.soft_delete``.

    Returns a one-element list ``[{'jti': ..., 'exp': ...}]`` when the Bearer
    access token is present, valid, and belongs to ``user_id``; otherwise ``None``.
    """
    try:
        from mobile_api.helpers.auth import (
            TOKEN_TYPE_ACCESS,
            get_token_from_request,
            verify_token,
        )

        token = get_token_from_request(request)
        if not token:
            return None
        payload = verify_token(token, expected_type=TOKEN_TYPE_ACCESS)
        if not payload:
            return None
        if str(payload.get('user_id') or '').strip() != str(user_id).strip():
            return None
        jti = str(payload.get('jti') or '').strip()
        if not jti:
            return None
        return [{'jti': jti, 'exp': payload.get('exp')}]
    except Exception:
        return None


def driver_delete_account(request, tenant_user, password: str) -> dict:
    """
    Soft-delete the driver's ``TenantUser`` after password confirmation.

    Uses ``TenantUser.soft_delete()`` only (no hard delete). Blacklists the
    current access-token JTI when it can be read from ``request``. Sets linked
    ``DriverMaster.driver_status`` to Inactive (row retained; not soft-deleted).

    Returns:
        {'success': True, 'message': lazy_str}
        {'success': False, 'error': lazy_str}
    """
    tenant_schema = _tenant_schema_from_driver_request(request)
    if not tenant_schema:
        return {'success': False, 'error': _('mobile.auth.unauthorized')}

    try:
        from tenant_workspace.models import DriverMaster, TenantUser

        with schema_context(tenant_schema):
            with transaction.atomic():
                row = (
                    TenantUser.all_objects.select_for_update()
                    .filter(pk=tenant_user.pk)
                    .first()
                )
                if row is None:
                    return {'success': False, 'error': _('mobile.auth.unauthorized')}
                if getattr(row, 'is_deleted', False):
                    return {'success': False, 'error': _('mobile.auth.account_already_deleted')}
                if not check_password(password, row.password_hash):
                    return {'success': False, 'error': _('mobile.auth.invalid_credentials')}

                mobile_tokens = _access_token_blacklist_entries_for_user(request, row.pk)
                row.soft_delete(
                    deleted_by=None,
                    mobile_tokens_to_blacklist=mobile_tokens,
                )

                driver = DriverMaster.objects.filter(user_account_id=row.pk).first()
                if driver is not None:
                    driver.driver_status = DriverMaster.Status.INACTIVE
                    driver.updated_at = timezone.now()
                    driver.save(update_fields=['driver_status', 'updated_at'])

        return {
            'success': True,
            'message': _('mobile.auth.account_deleted_success'),
        }
    except Exception as exc:
        logger.error('driver_delete_account error: %s', exc)
        return {'success': False, 'error': _('mobile.auth.unauthorized')}


# ── API 5: Logout ─────────────────────────────────────────────────

def driver_logout(
    user_id: str,
    jti: str,
    tenant_schema: str,
    exp_ts: int | None = None,
) -> dict:
    """
    Logout driver by revoking JWT from Redis.

    Uses existing redis_helpers.revoke_tenant_session_by_jti
    to invalidate the token JTI.

    Returns:
        {'success': True}
    """
    try:
        from mobile_api.helpers.auth import blacklist_token_jti
        from superadmin.redis_helpers import (
            revoke_tenant_session_by_jti,
        )
        blacklist_token_jti(jti=jti, exp_ts=exp_ts)
        revoke_tenant_session_by_jti(jti)
    except Exception as e:
        logger.error('Logout revoke error: %s', e)
        # Still return success — token will expire naturally

    return {'success': True}
