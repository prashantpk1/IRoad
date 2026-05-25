"""

Django system checks for mobile API production hardening.



Registered from ``MobileApiConfig.ready``. Run::



    python manage.py check

    python manage.py check --deploy

"""

from __future__ import annotations



from django.conf import settings

from django.core.checks import Error, Warning, register, Tags





@register(Tags.security, deploy=True)

def mobile_api_jwt_production_settings(app_configs, **kwargs):

    """Require issuer, audience, and dedicated signing key outside DEBUG."""

    errors: list = []

    if settings.DEBUG:

        return errors



    iss = (getattr(settings, 'MOBILE_API_JWT_ISS', None) or '').strip()

    aud = (getattr(settings, 'MOBILE_API_JWT_AUD', None) or '').strip()

    if not iss:

        errors.append(

            Error(

                'MOBILE_API_JWT_ISS must be set to a non-empty string when DEBUG is False.',

                hint='Set MOBILE_API_JWT_ISS (e.g. https://api.example.com/mobile) in the environment.',

                id='mobile_api.E001',

            )

        )

    if not aud:

        errors.append(

            Error(

                'MOBILE_API_JWT_AUD must be set to a non-empty string when DEBUG is False.',

                hint='Set MOBILE_API_JWT_AUD (e.g. iroad-mobile-app) in the environment.',

                id='mobile_api.E002',

            )

        )



    key = (getattr(settings, 'MOBILE_API_JWT_SIGNING_KEY', None) or '').strip()

    min_len = int(getattr(settings, 'MOBILE_API_JWT_SIGNING_KEY_MIN_LENGTH', 32) or 32)

    if len(key) < min_len:

        errors.append(

            Error(

                f'MOBILE_API_JWT_SIGNING_KEY must be at least {min_len} characters when DEBUG is False '

                '(do not rely on SECRET_KEY fallback in production).',

                hint='Generate a dedicated high-entropy key and set MOBILE_API_JWT_SIGNING_KEY.',

                id='mobile_api.E003',

            )

        )



    if not getattr(settings, 'MOBILE_API_JWT_DENY_ON_REDIS_READ_ERROR', False):

        errors.append(

            Warning(

                'MOBILE_API_JWT_DENY_ON_REDIS_READ_ERROR is False while DEBUG is False.',

                hint='Set MOBILE_API_JWT_DENY_ON_REDIS_READ_ERROR=True so Redis read failures '

                'cannot turn revoked tokens back into valid tokens.',

                id='mobile_api.W004',

            )

        )



    if not getattr(settings, 'MOBILE_API_REFRESH_REQUIRE_REDIS', False):

        errors.append(

            Warning(

                'MOBILE_API_REFRESH_REQUIRE_REDIS is False while DEBUG is False.',

                hint='Set MOBILE_API_REFRESH_REQUIRE_REDIS=True in production so refresh rotation '

                'cannot bypass Redis one-time consumption.',

                id='mobile_api.W005',

            )

        )



    return errors





@register(Tags.security, deploy=True)

def mobile_api_cors_production(app_configs, **kwargs):

    errors: list = []

    if settings.DEBUG:

        return errors

    if getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False):

        errors.append(

            Error(

                'CORS_ALLOW_ALL_ORIGINS must be False when DEBUG is False.',

                hint='Set CORS_ALLOW_ALL_ORIGINS=False and CORS_ALLOWED_ORIGINS to explicit https:// origins.',

                id='mobile_api.E010',

            )

        )

    origins = getattr(settings, 'CORS_ALLOWED_ORIGINS', None) or []

    if not origins:

        errors.append(

            Warning(

                'CORS_ALLOWED_ORIGINS is empty while DEBUG is False.',

                hint='Hybrid / WebView clients need explicit origins. Native-only apps may ignore.',

                id='mobile_api.W011',

            )

        )

    return errors





@register(Tags.security, deploy=True)

def mobile_api_allowed_hosts(app_configs, **kwargs):

    warnings: list = []

    if settings.DEBUG:

        return warnings

    hosts = getattr(settings, 'ALLOWED_HOSTS', []) or []

    if any(h == '*' for h in hosts):

        warnings.append(

            Warning(

                'ALLOWED_HOSTS contains "*" while DEBUG is False.',

                hint='Use explicit hostnames / domains for production.',

                id='mobile_api.W020',

            )

        )

    return warnings





@register(Tags.security)

def mobile_api_dashboard_capability_registered(app_configs, **kwargs):

    """Ensure driver dashboard capability is present in RBAC registry."""

    from mobile_api.rbac import CAPABILITY_GROUPS



    errors: list = []

    if 'mobile.driver.dashboard' not in CAPABILITY_GROUPS:

        errors.append(

            Error(

                'RBAC capability mobile.driver.dashboard is not registered.',

                hint='Add mobile.driver.dashboard to mobile_api.rbac.CAPABILITY_GROUPS.',

                id='mobile_api.E040',

            )

        )

    return errors





@register(Tags.security, deploy=True)

def mobile_api_password_reset_tenant_policy(app_configs, **kwargs):

    warnings: list = []

    if settings.DEBUG:

        return warnings

    if getattr(settings, 'MOBILE_API_PASSWORD_RESET_ALLOW_CROSS_TENANT_DISCOVERY', False):

        warnings.append(

            Warning(

                'MOBILE_API_PASSWORD_RESET_ALLOW_CROSS_TENANT_DISCOVERY is True while DEBUG is False.',

                hint='Disable cross-tenant OTP/email discovery in production; rely on '

                'X-Tenant-ID / tenant_id / request.tenant only.',

                id='mobile_api.W030',

            )

        )

    return warnings


DASHBOARD_PUBLIC_INDEXES = (
    'comm_push_token_drv_lookup_idx',
    'comm_push_rcpt_drv_lookup_idx',
)


@register(Tags.database, deploy=True)
def mobile_api_dashboard_index_readiness(app_configs, **kwargs):
    """Warn when dashboard public-schema indexes are missing."""
    warnings: list = []
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            for idx in DASHBOARD_PUBLIC_INDEXES:
                cursor.execute(
                    'SELECT 1 FROM pg_indexes WHERE schemaname = %s AND indexname = %s LIMIT 1',
                    ['public', idx],
                )
                if cursor.fetchone() is None:
                    warnings.append(
                        Warning(
                            f'Dashboard public index {idx} is missing.',
                            hint='Run migrate superadmin 0038 and '
                            'python manage.py verify_dashboard_readiness',
                            id='mobile_api.W050',
                        )
                    )
    except Exception:
        pass
    return warnings


JOB_LIST_TENANT_INDEXES = (
    'tenant_ship_drv_no_idx',
    'tenant_tml_drv_mno_idx',
    'tenant_tml_drv_src_idx',
    'tenant_oal_move_drv_date_idx',
    'tenant_ship_drv_rank_upd_idx',
)

JOB_LIST_TENANT_MIGRATIONS = (
    ('tenant_workspace', '0088_job_list_search_indexes'),
    ('tenant_workspace', '0089_job_list_movement_action_log_index'),
    ('tenant_workspace', '0090_shipment_mobile_operational_rank'),
)


@register(Tags.security, deploy=True)
def mobile_api_jobs_capability_registered(app_configs, **kwargs):
    errors: list = []
    try:
        from mobile_api.rbac import CAPABILITY_GROUPS

        found = any(
            cap.get('code') == 'mobile.driver.jobs'
            for group in CAPABILITY_GROUPS
            for cap in group.get('capabilities', [])
        )
        if not found:
            errors.append(
                Error(
                    'RBAC capability mobile.driver.jobs is not registered.',
                    hint='Add mobile.driver.jobs to mobile_api.rbac.CAPABILITY_GROUPS.',
                    id='mobile_api.E041',
                )
            )
    except Exception:
        pass
    return errors


@register(Tags.database, deploy=True)
def mobile_api_jobs_index_readiness(app_configs, **kwargs):
    """Fail deploy check when job-list migrations/indexes are missing (sample schema)."""
    from django.db import connection

    from mobile_api.helpers.job_list_readiness import (
        audit_schema,
        list_tenant_schemas,
    )

    errors: list = []
    warnings: list = []
    try:
        schemas = list_tenant_schemas()
        if not schemas:
            warnings.append(
                Warning(
                    'No tenant schemas found for job-list index audit.',
                    id='mobile_api.W061',
                )
            )
            return warnings
        with connection.cursor() as cursor:
            report = audit_schema(cursor, schemas[0])
        if not report.ready:
            for key, ok in report.migration_ok.items():
                if not ok:
                    errors.append(
                        Error(
                            f'Job list migration {key} missing on schema {report.schema}.',
                            hint='python manage.py migrate_job_list_tenants --apply',
                            id='mobile_api.E042',
                        )
                    )
            for idx, ok in report.index_ok.items():
                if not ok:
                    errors.append(
                        Error(
                            f'Job list index {idx} missing on schema {report.schema}.',
                            hint='python manage.py verify_job_list_readiness',
                            id='mobile_api.E043',
                        )
                    )
    except Exception:
        pass
    return errors + warnings


