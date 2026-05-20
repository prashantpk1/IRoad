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
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from django.utils.translation import gettext as _
from django_tenants.utils import schema_context

from mobile_api.helpers.auth import (
    TOKEN_TYPE_REFRESH,
    bind_refresh_family_head,
    blacklist_token_jti,
    clear_refresh_family_binding,
    generate_token_pair,
    mark_refresh_family_invalidated,
    try_consume_refresh_jti_once,
    verify_token,
)
from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.helpers.mobile_tenant import resolve_active_tenant_registry
from mobile_api.serializers.localized import serialize_localized_name
from mobile_api.models import DriverPasswordResetOTP

logger = logging.getLogger('mobile_api')


def _password_reset_allows_cross_tenant_discovery() -> bool:
    """
    Legacy opt-in: scan all tenant schemas to resolve email / OTP without a hint.

    Default **False** — production must resolve tenant from ``X-Tenant-ID`` /
    ``tenant_id`` / ``request.tenant`` only.
    """
    return bool(
        getattr(
            settings,
            'MOBILE_API_PASSWORD_RESET_ALLOW_CROSS_TENANT_DISCOVERY',
            False,
        )
    )


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


def _client_ip_from_request(request) -> str:
    """Best-effort client IP for audit (respects common proxy header)."""
    if request is None:
        return ''
    try:
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return (xff.split(',')[0] or '').strip()[:45]
        return (request.META.get('REMOTE_ADDR') or '').strip()[:45]
    except Exception:
        return ''


def _audit_mobile_session(
    event: str,
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    extra: str = '',
) -> None:
    """Structured session audit (no tokens or raw secrets)."""
    ip = _client_ip_from_request(request)
    logger.info(
        'mobile.session event=%s user_id=%s schema=%s ip=%s %s',
        event,
        user_id,
        tenant_schema,
        ip or '-',
        extra.strip(),
    )


def _mobile_login_lockout_settings() -> tuple[int, int]:
    max_attempts = int(
        getattr(settings, 'MOBILE_API_LOGIN_MAX_ATTEMPTS', 10) or 10
    )
    lockout_minutes = int(
        getattr(settings, 'MOBILE_API_LOGIN_LOCKOUT_MINUTES', 15) or 15
    )
    return max_attempts, lockout_minutes


def _schema_eligible_for_driver_login(
    email_norm: str,
    password: str,
    schema_name: str,
) -> bool:
    """
    True when this schema has a driver-ready account for email+password.

    Used only for **tenant discovery** (auto mode) and ambiguous detection —
    not a substitute for the transactional login checks (lockout, audit).
    """
    try:
        from tenant_workspace.models import DriverMaster, TenantUser

        with schema_context(schema_name):
            tenant_user = TenantUser.all_objects.filter(
                email__iexact=email_norm,
            ).first()
            if tenant_user is None or getattr(tenant_user, 'is_deleted', False):
                return False
            if not check_password(password, tenant_user.password_hash):
                return False
            if tenant_user.status != TenantUser.Status.ACTIVE:
                return False
            driver = DriverMaster.objects.filter(
                user_account_id=tenant_user.pk,
            ).first()
            if driver is None or str(driver.driver_status) != DriverMaster.Status.ACTIVE:
                return False
        return True
    except Exception:
        return False


def _list_eligible_login_schemas(email_norm: str, password: str) -> list[str]:
    """Deterministic list of schemas where credentials are valid for an active driver."""
    try:
        from iroad_tenants.models import TenantRegistry

        out: list[str] = []
        registries = (
            TenantRegistry.objects.select_related('tenant_profile')
            .order_by('schema_name')
        )
        for reg in registries:
            profile = getattr(reg, 'tenant_profile', None)
            if profile and getattr(profile, 'account_status', None) != 'Active':
                continue
            if _schema_eligible_for_driver_login(
                email_norm,
                password,
                reg.schema_name,
            ):
                out.append(reg.schema_name)
        return out
    except Exception as exc:
        logger.error('_list_eligible_login_schemas error: %s', exc)
        return []


def _ambiguous_candidate_payload(schema_name: str) -> dict:
    """Minimal tenant disambiguation payload for mobile (no secrets)."""
    try:
        from iroad_tenants.models import TenantRegistry

        reg = (
            TenantRegistry.objects.select_related('tenant_profile')
            .filter(schema_name=schema_name)
            .first()
        )
        if reg is None:
            return {
                'tenant_id': '',
                'schema_name': schema_name,
                'company_name': '',
            }
        tp = reg.tenant_profile
        return {
            'tenant_id': str(reg.tenant_profile_id),
            'schema_name': reg.schema_name,
            'company_name': (tp.company_name or '') if tp else '',
        }
    except Exception:
        return {
            'tenant_id': '',
            'schema_name': schema_name,
            'company_name': '',
        }


def _schema_eligible_for_driver_password_reset(
    email_norm: str,
    schema_name: str,
) -> bool:
    """True when this schema has an active driver account for the email."""
    try:
        from tenant_workspace.models import DriverMaster, TenantUser

        with schema_context(schema_name):
            tenant_user = TenantUser.all_objects.filter(
                email__iexact=email_norm,
            ).first()
            if tenant_user is None or getattr(tenant_user, 'is_deleted', False):
                return False
            if tenant_user.status != TenantUser.Status.ACTIVE:
                return False
            driver = DriverMaster.objects.filter(
                user_account_id=tenant_user.pk,
            ).first()
            if driver is None or str(driver.driver_status) != DriverMaster.Status.ACTIVE:
                return False
        return True
    except Exception:
        return False


def _list_eligible_password_reset_schemas(email_norm: str) -> list[str]:
    """Schemas where ``email`` belongs to an active driver (deterministic order)."""
    try:
        from iroad_tenants.models import TenantRegistry

        out: list[str] = []
        registries = (
            TenantRegistry.objects.select_related('tenant_profile')
            .order_by('schema_name')
        )
        for reg in registries:
            profile = getattr(reg, 'tenant_profile', None)
            if profile and getattr(profile, 'account_status', None) != 'Active':
                continue
            if _schema_eligible_for_driver_password_reset(
                email_norm,
                reg.schema_name,
            ):
                out.append(reg.schema_name)
        return out
    except Exception as exc:
        logger.error('_list_eligible_password_reset_schemas error: %s', exc)
        return []


def resolve_driver_password_reset_tenant(
    email: str,
    *,
    explicit_tenant: str,
) -> dict:
    """
    Resolve tenant for forgot-password (email only, no password).

    Mirrors ``resolve_driver_login_tenant``: optional explicit ``tenant_id`` from
    the JSON body only; otherwise auto-discovery across active subscribers.
    """
    email_norm = (email or '').strip().lower()
    explicit = (explicit_tenant or '').strip()

    if explicit:
        reg = resolve_active_tenant_registry(explicit)
        if reg is None:
            return {
                'ok': False,
                'error_code': 'invalid_tenant',
                'error': _('mobile.auth.invalid_tenant'),
            }
        schema = reg.schema_name
        if not _schema_eligible_for_driver_password_reset(email_norm, schema):
            return {
                'ok': True,
                'schema_name': schema,
                'mode': 'explicit_no_driver',
            }
        return {'ok': True, 'schema_name': schema, 'mode': 'explicit'}

    eligible = _list_eligible_password_reset_schemas(email_norm)
    if not eligible:
        return {'ok': True, 'schema_name': '', 'mode': 'none'}

    if len(eligible) == 1:
        return {'ok': True, 'schema_name': eligible[0], 'mode': 'auto'}

    candidates = [_ambiguous_candidate_payload(s) for s in eligible]
    candidates.sort(
        key=lambda c: (
            (c.get('company_name') or '').lower(),
            c.get('schema_name') or '',
        )
    )
    return {
        'ok': False,
        'error_code': 'tenant_ambiguous',
        'error': _('mobile.auth.tenant_ambiguous'),
        'candidates': candidates,
    }


def resolve_driver_login_tenant(
    email: str,
    password: str,
    *,
    explicit_tenant: str,
) -> dict:
    """
    Resolve which tenant schema to use for driver login.

    - **Explicit** ``tenant_id`` / header / middleware: only that registry is
      considered — no cross-tenant "first match wins" ambiguity.
    - **Auto** (no hint): all active registries are scanned in deterministic
      ``schema_name`` order; zero matches → invalid credentials; multiple
      eligible matches → ``tenant_ambiguous`` with a sorted candidate list.

    When ``MOBILE_API_LOGIN_REQUIRE_EXPLICIT_TENANT`` is true, auto mode is
    disabled: clients must send ``tenant_id`` or ``X-Tenant-ID``.
    """
    email_norm = (email or '').strip().lower()
    explicit = (explicit_tenant or '').strip()
    if getattr(settings, 'MOBILE_API_LOGIN_REQUIRE_EXPLICIT_TENANT', False):
        if not explicit:
            return {
                'ok': False,
                'error_code': 'tenant_required',
                'error': _('mobile.auth.tenant_required'),
            }
    if explicit:
        reg = resolve_active_tenant_registry(explicit)
        if reg is None:
            return {
                'ok': False,
                'error_code': 'invalid_tenant',
                'error': _('mobile.auth.invalid_tenant'),
            }
        if not _schema_eligible_for_driver_login(
            email_norm,
            password,
            reg.schema_name,
        ):
            return {
                'ok': False,
                'error_code': 'invalid_credentials',
                'error': _('mobile.auth.invalid_credentials'),
            }
        return {'ok': True, 'schema_name': reg.schema_name, 'mode': 'explicit'}

    eligible = _list_eligible_login_schemas(email_norm, password)
    if not eligible:
        return {
            'ok': False,
            'error_code': 'invalid_credentials',
            'error': _('mobile.auth.invalid_credentials'),
        }
    if len(eligible) == 1:
        return {'ok': True, 'schema_name': eligible[0], 'mode': 'auto'}

    candidates = [_ambiguous_candidate_payload(s) for s in eligible]
    candidates.sort(key=lambda c: ((c.get('company_name') or '').lower(), c.get('schema_name') or ''))
    return {
        'ok': False,
        'error_code': 'tenant_ambiguous',
        'error': _('mobile.auth.tenant_ambiguous'),
        'candidates': candidates,
    }


def resolve_tenant_schema_for_email(email: str) -> str | None:
    """
    Auto-detect tenant schema from email only when **uniquely** resolvable.

    Returns ``schema_name`` when exactly one active tenant contains this user;
    returns ``None`` when none exist or when **multiple** tenants match (caller
    must require an explicit ``tenant_id`` / ``X-Tenant-ID``).
    """
    sch, kind = resolve_tenant_schema_for_email_with_kind(email)
    if kind == 'unique':
        return sch
    return None


def resolve_tenant_schema_for_email_with_kind(
    email: str,
) -> tuple[str | None, str]:
    """
    Returns ``(schema_name, kind)`` where ``kind`` is ``unique``, ``none``, or
    ``ambiguous`` (multiple active tenants contain this email).
    """
    try:
        from iroad_tenants.models import TenantRegistry
        from tenant_workspace.models import TenantUser

        matches: list[str] = []
        registries = TenantRegistry.objects.select_related(
            'tenant_profile'
        ).order_by('schema_name')
        normalized_email = email.strip().lower()

        for reg in registries:
            try:
                profile = getattr(reg, 'tenant_profile', None)
                if profile and getattr(profile, 'account_status', None) != 'Active':
                    continue
                with schema_context(reg.schema_name):
                    exists = TenantUser.all_objects.filter(
                        email__iexact=normalized_email,
                    ).exists()
                    if exists:
                        matches.append(reg.schema_name)
            except Exception:
                continue
        if len(matches) == 1:
            return matches[0], 'unique'
        if len(matches) > 1:
            return None, 'ambiguous'
        return None, 'none'
    except Exception as e:
        logger.error('resolve_tenant_schema_for_email_with_kind error: %s', e)
        return None, 'none'


def resolve_tenant_schema_for_otp(
    email: str,
    otp_code: str,
    otp_status: str,
) -> str | None:
    """
    Find tenant schema by matching OTP record across active tenant schemas.

    Returns a schema only when **exactly one** tenant has a matching row;
    otherwise ``None`` (ambiguous or missing — caller should require explicit
    tenant context).
    """
    sch, kind = resolve_tenant_schema_for_otp_with_kind(email, otp_code, otp_status)
    if kind == 'unique':
        return sch
    return None


def _list_otp_match_schemas(
    email: str,
    otp_code: str,
    otp_status: str,
) -> list[str]:
    """All tenant schemas with a matching OTP row (deterministic order)."""
    matches: list[str] = []
    try:
        from iroad_tenants.models import TenantRegistry

        registries = TenantRegistry.objects.select_related(
            'tenant_profile'
        ).order_by('schema_name')
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
                        matches.append(reg.schema_name)
            except Exception:
                continue
    except Exception as e:
        logger.error('_list_otp_match_schemas error: %s', e)
    return matches


def resolve_tenant_schema_for_otp_with_kind(
    email: str,
    otp_code: str,
    otp_status: str,
) -> tuple[str | None, str]:
    """Returns ``(schema, 'unique'|'none'|'ambiguous')``."""
    matches = _list_otp_match_schemas(email, otp_code, otp_status)
    if len(matches) == 1:
        return matches[0], 'unique'
    if len(matches) > 1:
        return None, 'ambiguous'
    return None, 'none'


def build_token_claims(
    tenant_schema: str,
    tenant_user,
    driver,
    *,
    refresh_family_id: str | None = None,
) -> dict:
    """Build essential identity claims for mobile JWT payload (access + refresh)."""
    claims = {
        'email': tenant_user.email,
        'username': tenant_user.username,
        'full_name': tenant_user.full_name,
        'role_name': tenant_user.role_name,
        'driver_id': str(driver.driver_id),
        'driver_code': driver.driver_code,
        'token_version': int(getattr(tenant_user, 'mobile_token_version', 0) or 0),
    }
    try:
        from mobile_api.rbac import compute_is_admin_claim

        claims['is_admin'] = bool(compute_is_admin_claim(tenant_user))
    except Exception as exc:
        logger.error('build_token_claims is_admin error: %s', exc)
        claims['is_admin'] = False
    fam = (refresh_family_id or '').strip()
    if fam:
        claims['rt_fam'] = fam
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
    exp_m = int(
        getattr(settings, 'MOBILE_API_PASSWORD_RESET_OTP_EXPIRY_MINUTES', 10) or 10,
    )
    context_dict['otp_expires_minutes'] = exp_m
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
            f'Your verification code is {otp_code}. It expires in {exp_m} minutes.',
            (
                f'<p>Your verification code is <strong>{otp_code}</strong>.</p>'
                f'<p>This code expires in {exp_m} minutes.</p>'
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


def _clear_expired_login_lockout(tenant_user, max_attempts: int, lockout_minutes: int) -> None:
    """Reset counter when the lockout window has passed (best-effort in-DB)."""
    if max_attempts <= 0 or lockout_minutes <= 0:
        return
    attempts = int(tenant_user.login_attempts or 0)
    if attempts < max_attempts:
        return
    last_fail = tenant_user.last_failed_login_at
    if last_fail is None:
        return
    if timezone.now() >= last_fail + timedelta(minutes=lockout_minutes):
        tenant_user.login_attempts = 0
        tenant_user.last_failed_login_at = None
        tenant_user.save(
            update_fields=['login_attempts', 'last_failed_login_at', 'updated_at'],
        )


def _is_login_locked(tenant_user, max_attempts: int, lockout_minutes: int) -> bool:
    if max_attempts <= 0:
        return False
    attempts = int(tenant_user.login_attempts or 0)
    if attempts < max_attempts:
        return False
    if lockout_minutes <= 0:
        return True
    last_fail = tenant_user.last_failed_login_at
    if last_fail is None:
        return False
    return timezone.now() < last_fail + timedelta(minutes=lockout_minutes)


def driver_login(
    email: str,
    password: str,
    tenant_schema: str,
    *,
    request=None,
    device: dict | None = None,
) -> dict:
    """
    Authenticate driver by email + password with transactional lockout + audit.

    ``tenant_schema`` should be the resolved hint (body ``tenant_id``, header
    ``X-Tenant-ID``, or middleware). When empty, tenant is resolved from
    credentials across active subscribers (see ``resolve_driver_login_tenant``).

    Returns:
        {'success': True, 'data': {...mobile session envelope...}}
        {'success': False, 'error': lazy_str, 'error_code': str, ...}
    """
    max_attempts, lockout_minutes = _mobile_login_lockout_settings()
    email_norm = (email or '').strip().lower()
    ip = _client_ip_from_request(request)
    device = device or {}

    try:
        from mobile_api.helpers.login_throttle import (
            driver_login_burst_allow,
            driver_login_burst_record,
        )

        if not driver_login_burst_allow(email=email_norm, request=request):
            logger.info(
                'mobile.driver_login burst_rate_limited ip=%s',
                ip or '-',
            )
            return {
                'success': False,
                'error': _('mobile.auth.invalid_credentials'),
                'error_code': 'invalid_credentials',
            }
        driver_login_burst_record(email=email_norm, request=request)
    except Exception as exc:
        logger.error('driver_login burst throttle error: %s', exc)

    resolution = resolve_driver_login_tenant(
        email,
        password,
        explicit_tenant=(tenant_schema or '').strip(),
    )
    if not resolution.get('ok'):
        err_code = resolution.get('error_code', 'auth_failed')
        out = {
            'success': False,
            'error': resolution.get('error', _('mobile.auth.invalid_credentials')),
            'error_code': err_code,
        }
        if err_code == 'tenant_ambiguous':
            out['candidates'] = resolution.get('candidates') or []
        logger.info(
            'mobile.driver_login tenant_resolution_failed code=%s ip=%s',
            err_code,
            ip or '-',
        )
        return out

    tenant_schema = resolution['schema_name']
    mode = resolution.get('mode', 'auto')

    try:
        from tenant_workspace.models import DriverMaster, TenantUser
    except Exception as exc:
        logger.error('driver_login import error: %s', exc)
        return {
            'success': False,
            'error': _('mobile.auth.invalid_credentials'),
            'error_code': 'server_error',
        }

    with transaction.atomic():
        with schema_context(tenant_schema):
            tenant_user = (
                TenantUser.all_objects.select_for_update()
                .filter(email__iexact=email_norm)
                .first()
            )

            if tenant_user is None:
                logger.warning(
                    'mobile.driver_login no_user_after_resolution schema=%s mode=%s',
                    tenant_schema,
                    mode,
                )
                return {
                    'success': False,
                    'error': _('mobile.auth.invalid_credentials'),
                    'error_code': 'invalid_credentials',
                }

            _clear_expired_login_lockout(
                tenant_user,
                max_attempts,
                lockout_minutes,
            )
            tenant_user.refresh_from_db(
                fields=[
                    'login_attempts',
                    'last_failed_login_at',
                    'password_hash',
                    'status',
                    'is_deleted',
                    'mobile_token_version',
                ],
            )

            if _is_login_locked(tenant_user, max_attempts, lockout_minutes):
                logger.info(
                    'mobile.driver_login blocked_locked schema=%s user_id=%s ip=%s',
                    tenant_schema,
                    tenant_user.pk,
                    ip or '-',
                )
                return {
                    'success': False,
                    'error': _('mobile.auth.account_locked'),
                    'error_code': 'account_locked',
                }

            if getattr(tenant_user, 'is_deleted', False):
                logger.info(
                    'mobile.driver_login blocked_deleted schema=%s user_id=%s',
                    tenant_schema,
                    tenant_user.pk,
                )
                return {
                    'success': False,
                    'error': _('mobile.auth.account_deleted'),
                    'error_code': 'account_deleted',
                }

            if not check_password(password, tenant_user.password_hash):
                tenant_user.login_attempts = int(tenant_user.login_attempts or 0) + 1
                tenant_user.last_failed_login_at = timezone.now()
                tenant_user.save(
                    update_fields=[
                        'login_attempts',
                        'last_failed_login_at',
                        'updated_at',
                    ],
                )
                logger.warning(
                    'mobile.driver_login failed_password schema=%s user_id=%s ip=%s',
                    tenant_schema,
                    tenant_user.pk,
                    ip or '-',
                )
                return {
                    'success': False,
                    'error': _('mobile.auth.invalid_credentials'),
                    'error_code': 'invalid_credentials',
                }

            if tenant_user.status != TenantUser.Status.ACTIVE:
                return {
                    'success': False,
                    'error': _('mobile.auth.account_inactive'),
                    'error_code': 'account_inactive',
                }

            driver = (
                DriverMaster.objects.filter(user_account_id=tenant_user.pk)
                .select_related('nationality_country')
                .first()
            )
            if driver is None:
                return {
                    'success': False,
                    'error': _('mobile.auth.not_a_driver'),
                    'error_code': 'not_a_driver',
                }
            if str(driver.driver_status) != DriverMaster.Status.ACTIVE:
                return {
                    'success': False,
                    'error': _('mobile.auth.driver_inactive'),
                    'error_code': 'driver_inactive',
                }

            tenant_user.login_attempts = 0
            tenant_user.last_failed_login_at = None
            tenant_user.last_login_at = timezone.now()
            tenant_user.last_login_ip = ip
            tenant_user.save(
                update_fields=[
                    'login_attempts',
                    'last_failed_login_at',
                    'last_login_at',
                    'last_login_ip',
                    'updated_at',
                ],
            )

    refresh_family_id = str(uuid.uuid4())
    extra_claims = build_token_claims(
        tenant_schema=tenant_schema,
        tenant_user=tenant_user,
        driver=driver,
        refresh_family_id=refresh_family_id,
    )
    tokens = generate_token_pair(
        user_id=str(tenant_user.pk),
        tenant_schema=tenant_schema,
        extra_claims=extra_claims,
    )
    try:
        rp = verify_token(tokens['refresh_token'], expected_type=TOKEN_TYPE_REFRESH)
        if rp:
            bind_refresh_family_head(
                extra_claims.get('rt_fam', ''),
                str(rp.get('jti') or ''),
                rp.get('exp'),
            )
    except Exception:
        pass

    if device.get('platform') or device.get('device_id'):
        logger.info(
            'mobile.driver_login device schema=%s user_id=%s platform=%s',
            tenant_schema,
            tenant_user.pk,
            (device.get('platform') or '')[:64],
        )

    profile_block: dict = {}
    try:
        from mobile_api.services.driver_profile_service import get_driver_profile

        gp = get_driver_profile(
            user_id=str(tenant_user.pk),
            tenant_schema=tenant_schema,
            jwt_payload={'email': tenant_user.email},
            request=request,
        )
        if gp.get('success'):
            profile_block = gp.get('profile') or {}
    except Exception as exc:
        logger.error('driver_login profile enrich error: %s', exc)

    driver_data = profile_block.get('driver') if profile_block.get('driver') else {
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

    organization: dict = {}
    try:
        from iroad_tenants.models import TenantRegistry

        reg = (
            TenantRegistry.objects.select_related('tenant_profile')
            .filter(schema_name=tenant_schema)
            .first()
        )
        if reg and reg.tenant_profile:
            organization = {
                'tenant_id': str(reg.tenant_profile_id),
                'schema_name': reg.schema_name,
                'company_name': reg.tenant_profile.company_name or '',
            }
    except Exception as exc:
        logger.error('driver_login organization block error: %s', exc)

    permissions = {
        'role_name': tenant_user.role_name,
        'user_status': tenant_user.status,
        'driver_status': driver.driver_status,
    }

    data = {
        'access_token': tokens['access_token'],
        'refresh_token': tokens['refresh_token'],
        'token_type': 'Bearer',
        'expires_in': tokens['access_expires_in'],
        'refresh_expires_in': tokens['refresh_expires_in'],
        'driver': driver_data,
        'organization': organization,
        'assigned_truck': profile_block.get('current_truck'),
        'truck_type': profile_block.get('truck_type'),
        'assignment': profile_block.get('assignment'),
        'permissions': permissions,
        'profile': profile_block,
    }

    logger.info(
        'mobile.driver_login success schema=%s user_id=%s driver_id=%s ip=%s',
        tenant_schema,
        tenant_user.pk,
        driver.driver_id,
        ip or '-',
    )

    return {'success': True, 'data': data}


def driver_refresh_session(
    refresh_token: str,
    *,
    request=None,
    expected_tenant_schema: str = '',
) -> dict:
    """
    Rotate refresh token: verify, one-time consume (Redis), blacklist old refresh,
    issue new access + refresh with the same ``rt_fam`` (or a new family when
    migrating legacy tokens without ``rt_fam``).

    ``expected_tenant_schema`` when non-empty must match the token's
    ``tenant_schema`` (from ``X-Tenant-ID`` / middleware).
    """
    raw = (refresh_token or '').strip()
    if not raw:
        return {
            'success': False,
            'error': _('mobile.auth.refresh_invalid'),
            'error_code': 'refresh_invalid',
        }

    payload = verify_token(raw, expected_type=TOKEN_TYPE_REFRESH)
    if payload is None:
        return {
            'success': False,
            'error': _('mobile.auth.refresh_invalid'),
            'error_code': 'refresh_invalid',
        }

    user_id = str(payload.get('user_id') or '').strip()
    tenant_schema = str(payload.get('tenant_schema') or '').strip()
    old_jti = str(payload.get('jti') or '').strip()
    exp_ts = payload.get('exp')

    if not user_id or not tenant_schema or not old_jti:
        return {
            'success': False,
            'error': _('mobile.auth.refresh_invalid'),
            'error_code': 'refresh_invalid',
        }

    exp_hint = (expected_tenant_schema or '').strip()
    if exp_hint and exp_hint != tenant_schema:
        logger.info(
            'mobile.driver_refresh tenant_hint_mismatch expected=%s token_schema=%s',
            exp_hint,
            tenant_schema,
        )
        return {
            'success': False,
            'error': _('mobile.auth.tenant_mismatch'),
            'error_code': 'tenant_mismatch',
        }
    forced_hint = exp_hint or tenant_schema

    tenant_user, driver, err_msg, err_code = resolve_mobile_driver_session(
        request,
        payload,
        forced_tenant_hint=forced_hint,
    )
    if err_msg is not None:
        ec = err_code or 'refresh_invalid'
        if ec in ('token_invalid', 'not_a_driver', 'forbidden'):
            return {
                'success': False,
                'error': err_msg,
                'error_code': 'refresh_invalid',
            }
        return {
            'success': False,
            'error': err_msg,
            'error_code': ec,
        }

    if not try_consume_refresh_jti_once(old_jti, exp_ts):
        logger.warning(
            'mobile.driver_refresh replay_or_race schema=%s user_id=%s',
            tenant_schema,
            user_id,
        )
        try:
            from mobile_api.helpers.security_audit import log_mobile_security_event

            log_mobile_security_event(
                'jwt_refresh_replay_or_race',
                schema=tenant_schema,
                user_id=user_id,
                ip=_client_ip_from_request(request),
                reason='consume_refresh_nx_failed',
            )
        except Exception:
            pass
        return {
            'success': False,
            'error': _('mobile.auth.refresh_replay'),
            'error_code': 'refresh_replay',
        }

    rt_fam = (payload.get('rt_fam') or '').strip() or str(uuid.uuid4())
    extra_claims = build_token_claims(
        tenant_schema=tenant_schema,
        tenant_user=tenant_user,
        driver=driver,
        refresh_family_id=rt_fam,
    )

    tokens = generate_token_pair(
        user_id=str(tenant_user.pk),
        tenant_schema=tenant_schema,
        extra_claims=extra_claims,
    )

    blacklist_token_jti(jti=old_jti, exp_ts=exp_ts)
    try:
        from superadmin.redis_helpers import revoke_tenant_session_by_jti

        revoke_tenant_session_by_jti(old_jti)
    except Exception as exc:
        logger.error('driver_refresh_session revoke old jti error: %s', exc)

    try:
        rp = verify_token(tokens['refresh_token'], expected_type=TOKEN_TYPE_REFRESH)
        if rp:
            bind_refresh_family_head(
                rt_fam,
                str(rp.get('jti') or ''),
                rp.get('exp'),
            )
    except Exception:
        pass

    logger.info(
        'mobile.driver_refresh rotated schema=%s user_id=%s fam=%s',
        tenant_schema,
        user_id,
        rt_fam[:8] if rt_fam else '-',
    )

    return {
        'success': True,
        'data': {
            'access_token': tokens['access_token'],
            'refresh_token': tokens['refresh_token'],
            'token_type': 'Bearer',
            'expires_in': tokens['access_expires_in'],
            'refresh_expires_in': tokens['refresh_expires_in'],
        },
    }


# ── API 2: Forgot Password ────────────────────────────────────────

def driver_forgot_password(
    email: str,
    tenant_schema: str,
    *,
    request=None,
) -> dict:
    """
    Initiate password reset by sending OTP to the driver's email.

    Anti-enumeration: for every outcome except ``tenant_ambiguous_operation``,
    the API layer should present the same success envelope (see view). Unknown
    emails, non-drivers, resend cooldown, and cache rate limits all yield
    ``success=True`` with ``email_dispatch_status=False`` when no email is sent.
    """
    from mobile_api.helpers.password_reset_security import (
        audit_password_reset_event,
        forgot_password_rate_allow,
        forgot_password_rate_record_send,
        timing_jitter_small,
    )

    email_n = (email or '').strip().lower()

    def ok_no_send() -> dict:
        timing_jitter_small()
        return {'success': True, 'email_dispatch_status': False}

    ts_in = (tenant_schema or '').strip()
    if not ts_in:
        audit_password_reset_event(
            'forgot_no_matching_tenant',
            tenant_schema='',
            email=email_n,
            request=request,
        )
        return ok_no_send()

    if not forgot_password_rate_allow(
        email=email_n,
        tenant_schema=ts_in,
        request=request,
    ):
        audit_password_reset_event(
            'forgot_rate_limited',
            tenant_schema=ts_in,
            email=email_n,
            request=request,
        )
        return ok_no_send()

    tenant_user = get_driver_user_by_email(email_n, ts_in)
    if tenant_user is None:
        audit_password_reset_event(
            'forgot_no_user',
            tenant_schema=ts_in,
            email=email_n,
            request=request,
        )
        return ok_no_send()

    if getattr(tenant_user, 'is_deleted', False):
        audit_password_reset_event(
            'forgot_deleted_user',
            tenant_schema=ts_in,
            email=email_n,
            request=request,
        )
        return ok_no_send()

    driver = get_driver_master_by_user(tenant_user, ts_in)
    if driver is None:
        audit_password_reset_event(
            'forgot_not_driver',
            tenant_schema=ts_in,
            email=email_n,
            request=request,
        )
        return ok_no_send()

    if DriverPasswordResetOTP.resend_is_throttled(email_n, ts_in):
        audit_password_reset_event(
            'forgot_resend_throttled',
            tenant_schema=ts_in,
            email=email_n,
            request=request,
        )
        return ok_no_send()

    otp_code = generate_otp()
    DriverPasswordResetOTP.create_for_email(
        email=email_n,
        tenant_schema=ts_in,
        otp_code=otp_code,
    )

    email_sent = send_driver_reset_otp_email(
        recipient_email=email_n,
        otp_code=otp_code,
        tenant_schema=ts_in,
        user_name=getattr(tenant_user, 'full_name', '') or email_n,
    )
    if email_sent:
        forgot_password_rate_record_send(
            email=email_n,
            tenant_schema=ts_in,
            request=request,
        )
        audit_password_reset_event(
            'forgot_otp_sent',
            tenant_schema=ts_in,
            email=email_n,
            request=request,
        )
    else:
        audit_password_reset_event(
            'forgot_email_dispatch_failed',
            tenant_schema=ts_in,
            email=email_n,
            request=request,
        )
        logger.warning(
            'Password reset OTP email dispatch failed (schema=%s)',
            ts_in,
        )

    timing_jitter_small()
    return {'success': True, 'email_dispatch_status': bool(email_sent)}


# ── API 3: Verify OTP ─────────────────────────────────────────────

def _pwreset_otp_max_attempts() -> int:
    return int(getattr(settings, 'MOBILE_API_PASSWORD_RESET_OTP_MAX_ATTEMPTS', 5) or 5)


def driver_verify_otp(
    email: str,
    otp_code: str,
    tenant_schema: str,
    *,
    request=None,
) -> dict:
    """
    Verify OTP for password reset.

    Uses a single client-facing error copy (``otp_verify_failed``) except for
    ``tenant_ambiguous_operation``. Constant-time OTP compare, cache throttles,
    and per-row attempt limits mitigate brute-force and replay-style guessing.
    """
    from mobile_api.helpers.password_reset_security import (
        audit_password_reset_event,
        otp_compare_constant_time,
        timing_jitter_small,
        verify_otp_rate_allow,
        verify_otp_rate_record_attempt,
    )

    email_n = (email or '').strip().lower()
    otp_in = (otp_code or '').strip()

    def fail_verify() -> dict:
        timing_jitter_small()
        return {
            'success': False,
            'error': _('mobile.auth.otp_verify_failed'),
            'error_code': 'otp_verify_failed',
        }

    ts_work = (tenant_schema or '').strip()
    if not ts_work:
        sch, kind = resolve_tenant_schema_for_otp_with_kind(
            email=email_n,
            otp_code=otp_in,
            otp_status=DriverPasswordResetOTP.Status.PENDING,
        )
        if kind == 'ambiguous':
            audit_password_reset_event(
                'verify_tenant_ambiguous',
                tenant_schema='-',
                email=email_n,
                request=request,
            )
            timing_jitter_small()
            matches = _list_otp_match_schemas(
                email_n,
                otp_in,
                DriverPasswordResetOTP.Status.PENDING,
            )
            candidates = [_ambiguous_candidate_payload(s) for s in matches]
            candidates.sort(
                key=lambda c: (
                    (c.get('company_name') or '').lower(),
                    c.get('schema_name') or '',
                )
            )
            return {
                'success': False,
                'error': _('mobile.auth.tenant_ambiguous'),
                'error_code': 'tenant_ambiguous',
                'candidates': candidates,
            }
        ts_work = (sch or '').strip()

    rate_key = ts_work or '_'
    if not verify_otp_rate_allow(
        email=email_n,
        tenant_schema=rate_key,
        request=request,
    ):
        audit_password_reset_event(
            'verify_rate_limited',
            tenant_schema=rate_key,
            email=email_n,
            request=request,
        )
        return fail_verify()

    verify_otp_rate_record_attempt(
        email=email_n,
        tenant_schema=rate_key,
        request=request,
    )

    if not ts_work:
        audit_password_reset_event(
            'verify_no_tenant',
            tenant_schema='-',
            email=email_n,
            request=request,
        )
        return fail_verify()

    otp_record = DriverPasswordResetOTP.get_valid_otp(
        email=email_n,
        tenant_schema=ts_work,
    )

    if otp_record is None:
        audit_password_reset_event(
            'verify_no_pending_otp',
            tenant_schema=ts_work,
            email=email_n,
            request=request,
        )
        return fail_verify()

    if otp_record.is_expired:
        otp_record.status = DriverPasswordResetOTP.Status.EXPIRED
        with schema_context(ts_work):
            otp_record.save(update_fields=['status'])
        audit_password_reset_event(
            'verify_expired',
            tenant_schema=ts_work,
            email=email_n,
            request=request,
        )
        return fail_verify()

    max_at = _pwreset_otp_max_attempts()
    if otp_record.attempts >= max_at:
        audit_password_reset_event(
            'verify_max_attempts',
            tenant_schema=ts_work,
            email=email_n,
            request=request,
        )
        return fail_verify()

    if not otp_compare_constant_time(otp_record.otp_code, otp_in):
        otp_record.attempts += 1
        with schema_context(ts_work):
            otp_record.save(update_fields=['attempts'])
        audit_password_reset_event(
            'verify_otp_mismatch',
            tenant_schema=ts_work,
            email=email_n,
            request=request,
        )
        return fail_verify()

    otp_record.status = DriverPasswordResetOTP.Status.VERIFIED
    otp_record.verified_at = timezone.now()
    with schema_context(ts_work):
        otp_record.save(update_fields=['status', 'verified_at'])

    audit_password_reset_event(
        'verify_success',
        tenant_schema=ts_work,
        email=email_n,
        request=request,
    )
    timing_jitter_small()
    return {'success': True}


# ── API 4: Reset Password ─────────────────────────────────────────

def driver_reset_password(
    email: str,
    otp_code: str,
    new_password: str,
    tenant_schema: str,
    *,
    request=None,
) -> dict:
    """
    Reset password after OTP verification.

    Generic client errors (``reset_password_failed``) avoid leaking whether the
    email exists or which OTP state failed. Constant-time OTP compare; per-IP
    throttling; marking the OTP row ``USED`` prevents replay of the same code.
    """
    from mobile_api.helpers.password_reset_security import (
        audit_password_reset_event,
        otp_compare_constant_time,
        reset_password_rate_allow,
        reset_password_rate_record,
        timing_jitter_small,
    )

    email_n = (email or '').strip().lower()
    otp_in = (otp_code or '').strip()

    def fail_reset() -> dict:
        timing_jitter_small()
        return {
            'success': False,
            'error': _('mobile.auth.reset_password_failed'),
            'error_code': 'reset_password_failed',
        }

    ts_work = (tenant_schema or '').strip()
    if not ts_work:
        sch, kind = resolve_tenant_schema_for_otp_with_kind(
            email=email_n,
            otp_code=otp_in,
            otp_status=DriverPasswordResetOTP.Status.VERIFIED,
        )
        if kind == 'ambiguous':
            timing_jitter_small()
            matches = _list_otp_match_schemas(
                email_n,
                otp_in,
                DriverPasswordResetOTP.Status.VERIFIED,
            )
            candidates = [_ambiguous_candidate_payload(s) for s in matches]
            candidates.sort(
                key=lambda c: (
                    (c.get('company_name') or '').lower(),
                    c.get('schema_name') or '',
                )
            )
            return {
                'success': False,
                'error': _('mobile.auth.tenant_ambiguous'),
                'error_code': 'tenant_ambiguous',
                'candidates': candidates,
            }
        ts_work = (sch or '').strip()

    if not reset_password_rate_allow(request=request):
        audit_password_reset_event(
            'reset_rate_limited',
            tenant_schema=ts_work or '-',
            email=email_n,
            request=request,
        )
        return fail_reset()

    reset_password_rate_record(request=request)

    if not ts_work:
        audit_password_reset_event(
            'reset_no_tenant',
            tenant_schema='-',
            email=email_n,
            request=request,
        )
        return fail_reset()

    otp_record = DriverPasswordResetOTP.get_verified_otp(
        email=email_n,
        tenant_schema=ts_work,
    )

    if otp_record is None:
        audit_password_reset_event(
            'reset_no_verified_otp',
            tenant_schema=ts_work,
            email=email_n,
            request=request,
        )
        return fail_reset()

    if not otp_compare_constant_time(otp_record.otp_code, otp_in):
        audit_password_reset_event(
            'reset_otp_mismatch',
            tenant_schema=ts_work,
            email=email_n,
            request=request,
        )
        return fail_reset()

    if otp_record.is_expired:
        otp_record.status = DriverPasswordResetOTP.Status.EXPIRED
        with schema_context(ts_work):
            otp_record.save(update_fields=['status'])
        audit_password_reset_event(
            'reset_expired',
            tenant_schema=ts_work,
            email=email_n,
            request=request,
        )
        return fail_reset()

    tenant_user = get_driver_user_by_email(email_n, ts_work)
    if tenant_user is None or getattr(tenant_user, 'is_deleted', False):
        audit_password_reset_event(
            'reset_user_missing',
            tenant_schema=ts_work,
            email=email_n,
            request=request,
        )
        return fail_reset()

    from tenant_workspace.models import TenantUser as TenantUserModel

    with schema_context(ts_work):
        TenantUserModel.all_objects.filter(pk=tenant_user.pk).update(
            password_hash=make_password(new_password),
            mobile_token_version=F('mobile_token_version') + 1,
        )

    otp_record.status = DriverPasswordResetOTP.Status.USED
    otp_record.used_at = timezone.now()
    with schema_context(ts_work):
        otp_record.save(update_fields=['status', 'used_at'])
        DriverPasswordResetOTP.objects.filter(
            email=email_n,
            tenant_schema=ts_work,
            status=DriverPasswordResetOTP.Status.PENDING,
        ).update(status=DriverPasswordResetOTP.Status.EXPIRED)

    audit_password_reset_event(
        'reset_success',
        tenant_schema=ts_work,
        email=email_n,
        request=request,
    )
    logger.info(
        'mobile.session event=driver_password_reset schema=%s',
        ts_work,
    )
    timing_jitter_small()
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


def driver_logout_all_devices(
    *,
    user_id: str,
    tenant_schema: str,
    access_jti: str,
    access_exp_ts: int | None,
    access_rt_fam: str | None,
    refresh_token: str | None = None,
    request=None,
) -> dict:
    """
    Revoke **all** mobile sessions for this driver: blacklist current tokens,
    invalidate refresh families in Redis, increment ``mobile_token_version``.

    Optional ``refresh_token`` should be the current refresh JWT so it is
    blacklisted before the version bump (otherwise verify would fail after bump).
    """
    uid = str(user_id or '').strip()
    schema = str(tenant_schema or '').strip()
    if not uid or not schema:
        return {'success': False, 'error': _('mobile.auth.unauthorized')}

    rt_body = (refresh_token or '').strip()
    rp = None
    if rt_body:
        rp = verify_token(rt_body, expected_type=TOKEN_TYPE_REFRESH)
        if not rp or str(rp.get('user_id') or '').strip() != uid:
            rp = None
        elif str(rp.get('tenant_schema') or '').strip() != schema:
            rp = None

    fams: set[str] = set()
    af = (access_rt_fam or '').strip()
    if af:
        fams.add(af)
    if rp:
        rf = (rp.get('rt_fam') or '').strip()
        if rf:
            fams.add(rf)

    acc_jti = str(access_jti or '').strip()
    if acc_jti:
        try:
            from superadmin.redis_helpers import revoke_tenant_session_by_jti

            blacklist_token_jti(jti=acc_jti, exp_ts=access_exp_ts)
            revoke_tenant_session_by_jti(acc_jti)
        except Exception as exc:
            logger.error('logout_all access revoke error: %s', exc)

    if rp:
        rjti = str(rp.get('jti') or '').strip()
        if rjti:
            try:
                from superadmin.redis_helpers import revoke_tenant_session_by_jti

                blacklist_token_jti(jti=rjti, exp_ts=rp.get('exp'))
                revoke_tenant_session_by_jti(rjti)
            except Exception as exc:
                logger.error('logout_all refresh revoke error: %s', exc)

    for fam in fams:
        mark_refresh_family_invalidated(fam)
        clear_refresh_family_binding(fam)

    try:
        from tenant_workspace.models import TenantUser

        with schema_context(schema):
            with transaction.atomic():
                row = (
                    TenantUser.all_objects.select_for_update()
                    .filter(pk=uid)
                    .first()
                )
                if row is None:
                    return {'success': False, 'error': _('mobile.auth.unauthorized')}
                TenantUser.all_objects.filter(pk=uid).update(
                    mobile_token_version=F('mobile_token_version') + 1,
                )
    except Exception as exc:
        logger.error('driver_logout_all_devices db error: %s', exc)
        return {'success': False, 'error': _('mobile.auth.unauthorized')}

    _audit_mobile_session(
        'driver_logout_all',
        user_id=uid,
        tenant_schema=schema,
        request=request,
        extra='families=%s' % len(fams),
    )
    return {'success': True, 'data': {}}


def driver_logout(
    user_id: str,
    jti: str,
    tenant_schema: str,
    exp_ts: int | None = None,
    *,
    refresh_token: str | None = None,
    access_rt_fam: str | None = None,
    request=None,
) -> dict:
    """
    Single-device logout: blacklist access (and optional refresh) JTIs,
    mark ``rt_fam`` invalidated in Redis, clear family head binding.

    ``access_rt_fam`` should come from the verified access JWT claims so the
    access leg is revoked even if the client omits ``refresh_token``.
    """
    uid = str(user_id or '').strip()
    schema = str(tenant_schema or '').strip()
    fams: set[str] = set()
    af = (access_rt_fam or '').strip()
    if af:
        fams.add(af)

    try:
        from superadmin.redis_helpers import revoke_tenant_session_by_jti

        if (jti or '').strip():
            blacklist_token_jti(jti=jti, exp_ts=exp_ts)
            revoke_tenant_session_by_jti(jti)
    except Exception as e:
        logger.error('Logout revoke access error: %s', e)

    rt = (refresh_token or '').strip()
    if rt:
        try:
            rp = verify_token(rt, expected_type=TOKEN_TYPE_REFRESH)
            if (
                rp
                and str(rp.get('user_id') or '').strip() == uid
                and str(rp.get('tenant_schema') or '').strip() == schema
            ):
                rjti = str(rp.get('jti') or '').strip()
                if rjti:
                    blacklist_token_jti(jti=rjti, exp_ts=rp.get('exp'))
                    try:
                        from superadmin.redis_helpers import (
                            revoke_tenant_session_by_jti,
                        )

                        revoke_tenant_session_by_jti(rjti)
                    except Exception as exc:
                        logger.error('Logout revoke refresh error: %s', exc)
                fam = (rp.get('rt_fam') or '').strip()
                if fam:
                    fams.add(fam)
        except Exception as exc:
            logger.error('Logout refresh handling error: %s', exc)

    for fam in fams:
        mark_refresh_family_invalidated(fam)
        clear_refresh_family_binding(fam)

    _audit_mobile_session(
        'driver_logout',
        user_id=uid,
        tenant_schema=schema,
        request=request,
        extra='refresh_in_body=%s' % bool(rt),
    )
    return {'success': True}
