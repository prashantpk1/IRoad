"""
Middleware for the tenant web portal (``/tenant/`` URLs).
"""
from __future__ import annotations

from django.contrib import messages
from django.db import connection
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import translation

from iroad_tenants.subscription_access import (
    is_subscription_setup_request,
    tenant_has_active_subscription,
    tenant_portal_is_owner_admin,
)
from iroad_tenants.tenant_schema import lock_portal_tenant_schema, unlock_portal_tenant_schema
from iroad_tenants.tenant_system_config import (
    activate_tenant_system_config,
    resolve_tenant_system_config,
)
from superadmin.models import TenantProfile
from superadmin.redis_helpers import get_tenant_session
from superadmin.tenant_portal_auth import get_tenant_portal_cookie_payload


class TenantPortalSchemaMiddleware:
    """
    Keep the tenant workspace Postgres schema active for the entire portal request.

    Without this, context processors and helpers call ``set_schema_to_public()``
    during template rendering while form dropdowns still hold lazy querysets,
    causing ``InvalidCursorName`` and missing ``tenant_*`` table errors.
    """

    PREFIX = '/tenant/'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        locked = False
        if request.path.startswith(self.PREFIX):
            from iroad_tenants.views import _activate_tenant_workspace_schema

            registry = _activate_tenant_workspace_schema(
                request,
                _debug_label='[portal-mw]',
            )
            if registry is not None:
                lock_portal_tenant_schema(request, registry)
                locked = True
        try:
            return self.get_response(request)
        finally:
            if locked:
                unlock_portal_tenant_schema(request)


class TenantSubscriptionGateMiddleware:
    """
    Tenant owners without an active subscription may only open subscription
    setup pages until they purchase a plan.
    """

    PREFIX = '/tenant/'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(self.PREFIX):
            return self.get_response(request)

        if is_subscription_setup_request(request):
            return self.get_response(request)

        auth_payload = get_tenant_portal_cookie_payload(request) or {}
        tenant_id = auth_payload.get('tenant_id')
        tenant_jti = auth_payload.get('jti')
        if not tenant_id or not tenant_jti:
            return self.get_response(request)

        # TenantProfile lives in the public schema; portal schema may already be active.
        prior_tenant = getattr(connection, 'tenant', None)
        connection.set_schema_to_public()
        try:
            tenant = TenantProfile.objects.filter(pk=tenant_id).first()
        finally:
            if prior_tenant is not None:
                connection.set_tenant(prior_tenant)
            else:
                connection.set_schema_to_public()
        if tenant is None or tenant.account_status != 'Active':
            return self.get_response(request)

        session_data = get_tenant_session(str(tenant.tenant_id), str(tenant_jti)) or {}
        if not tenant_portal_is_owner_admin(session_data, tenant):
            return self.get_response(request)

        if tenant_has_active_subscription(tenant):
            return self.get_response(request)

        messages.warning(
            request,
            'Choose a subscription plan to access this area. '
            'Add a payment method on Subscription Billing before purchasing.',
            extra_tags='tenant',
        )
        return redirect(reverse('iroad_tenants:tenant_subscription_plan'))


class TenantSystemConfigurationMiddleware:
    """
    Apply Organization Profile system settings (timezone, language, formats)
    for every tenant portal request.
    """

    PREFIX = '/tenant/'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(self.PREFIX):
            return self.get_response(request)

        config = resolve_tenant_system_config(request)
        request.tenant_system_config = config

        from django.utils import timezone as dj_tz

        previous_tz = dj_tz.get_current_timezone()
        previous_language = translation.get_language()
        activate_tenant_system_config(config)
        try:
            return self.get_response(request)
        finally:
            dj_tz.activate(previous_tz)
            translation.activate(previous_language)
