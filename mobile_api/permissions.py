"""
mobile_api/permissions.py

DRF permission classes for the Mobile API.

Layering:
  1. ``IsMobileAuthenticated`` — valid JWT + driver session (from authentication).
  2. Role gates: ``IsDriver``, ``IsDispatcher``, ``IsTenantAdmin`` — enforce RBAC.
  3. ``HasViewMobileCapability`` — reads ``required_mobile_capability`` on the view.

RBAC rules live in ``mobile_api.rbac`` (capabilities, role groups, JWT helpers).
"""
from rest_framework.permissions import BasePermission
from django.utils.translation import gettext_lazy as _

from mobile_api.rbac import (
    get_mobile_jwt_payload,
    request_has_capability,
    user_in_dispatcher_group,
    user_in_driver_group,
    user_in_tenant_admin_group,
)


class IsMobileAuthenticated(BasePermission):
    """
    Allow access only to authenticated mobile users.
    Token must be present and valid.
    Applied globally via REST_FRAMEWORK settings.
    """
    message = _('mobile.auth.unauthorized')

    def has_permission(self, request, view):
        return (
            request.user is not None
            and hasattr(request.user, 'is_authenticated')
            and request.user.is_authenticated
        )


class AllowAnyMobile(BasePermission):
    """
    Allow any request — authenticated or not.
    Use on public endpoints like login, register, forgot password.

    Example:
        authentication_classes = []
        permission_classes = [AllowAnyMobile]
    """
    message = ''

    def has_permission(self, request, view):
        return True


class IsDriver(BasePermission):
    """
    **Driver mobile app** — JWT must represent an allowed driver principal
    (``driver_id`` + ``role_name`` per ``MOBILE_API_RBAC_DRIVER_ROLE_NAMES``).

    Use on endpoints that must never be callable by dispatchers/admins unless
    they also carry a driver session (they normally do not).
    """
    message = _('mobile.auth.driver_role_required')

    def has_permission(self, request, view):
        if not IsMobileAuthenticated().has_permission(request, view):
            return False
        return user_in_driver_group(request)


class IsDispatcher(BasePermission):
    """
    **Dispatcher** operational principal — ``role_name`` matches dispatcher CSV.

    Tenant admins do **not** pass this gate; use ``HasViewMobileCapability`` or
    combine permissions in the view if both dispatcher and admin should access.
    """
    message = _('mobile.auth.dispatcher_role_required')

    def has_permission(self, request, view):
        if not IsMobileAuthenticated().has_permission(request, view):
            return False
        return user_in_dispatcher_group(request)


class IsTenantAdmin(BasePermission):
    """
    **Tenant administrator** — JWT ``is_admin`` **or** ``role_name`` in admin CSV.

    Replaces legacy ``payload.is_admin``-only checks with explicit role mapping.
    """
    message = _('mobile.auth.admin_required')

    def has_permission(self, request, view):
        if not IsMobileAuthenticated().has_permission(request, view):
            return False
        return user_in_tenant_admin_group(request)


class HasViewMobileCapability(BasePermission):
    """
    Capability-based authorization.

    Set on the view::

        class MyView(MobileAPIView):
            required_mobile_capability = 'mobile.operations.read'

    If the attribute is missing, this permission **allows** (no-op) so base
    views are not broken — prefer setting the attribute explicitly.
    """
    message = _('mobile.auth.capability_denied')

    def has_permission(self, request, view):
        if not IsMobileAuthenticated().has_permission(request, view):
            return False
        cap = getattr(view, 'required_mobile_capability', None) or getattr(
            view,
            'mobile_capability',
            None,
        )
        if not cap:
            return True
        return request_has_capability(request, str(cap))


class HasDriverDashboardAccess(BasePermission):
    """
    Home dashboard gate: authenticated driver principal + ``mobile.driver.dashboard``
    capability + JWT tenant binding (prevents cross-tenant header tampering).

    Use on all ``/api/v1/mobile/driver/dashboard/*`` views instead of composing
    three permissions manually.
    """
    message = _('mobile.auth.dashboard_denied')

    def has_permission(self, request, view):
        if not IsMobileAuthenticated().has_permission(request, view):
            return False
        if not user_in_driver_group(request):
            return False
        cap = (
            getattr(view, 'required_mobile_capability', None)
            or getattr(view, 'mobile_capability', None)
            or 'mobile.driver.dashboard'
        )
        if not request_has_capability(request, str(cap)):
            return False
        payload = get_mobile_jwt_payload(request)
        tenant_schema = str(payload.get('tenant_schema') or '').strip()
        if not tenant_schema:
            return False
        from mobile_api.helpers.dashboard_security import (
            validate_dashboard_tenant_binding,
        )

        return validate_dashboard_tenant_binding(
            request,
            expected_schema=tenant_schema,
        )


class HasDriverJobsAccess(BasePermission):
    """
    Job list gate: authenticated driver + ``mobile.driver.jobs`` + JWT tenant binding.
    """

    message = _('mobile.auth.jobs_denied')

    def has_permission(self, request, view):
        if not IsMobileAuthenticated().has_permission(request, view):
            return False
        if not user_in_driver_group(request):
            return False
        cap = (
            getattr(view, 'required_mobile_capability', None)
            or getattr(view, 'mobile_capability', None)
            or 'mobile.driver.jobs'
        )
        if not request_has_capability(request, str(cap)):
            return False
        payload = get_mobile_jwt_payload(request)
        tenant_schema = str(payload.get('tenant_schema') or '').strip()
        if not tenant_schema:
            return False
        from mobile_api.helpers.job_list_security import validate_jobs_tenant_binding

        return validate_jobs_tenant_binding(
            request,
            expected_schema=tenant_schema,
        )


# Backwards-compatible alias (older imports / docs)
IsMobileDriver = IsDriver
IsMobileDispatcher = IsDispatcher
IsMobileTenantAdmin = IsTenantAdmin
