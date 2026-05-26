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


