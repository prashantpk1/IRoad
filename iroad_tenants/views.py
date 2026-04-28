import csv

import logging
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db import connection
from django.utils import timezone
import os
import uuid
from urllib.parse import quote
from superadmin.models import TenantProfile, TenantSecuritySettings
from superadmin.models import AdminUser, Country, Currency
from superadmin.redis_helpers import (
    get_tenant_session,
    refresh_tenant_session,
    revoke_tenant_session_key,
)
from superadmin.tenant_portal_auth import (
    clear_tenant_portal_cookie,
    get_tenant_portal_cookie_payload,
)
from superadmin.communication_helpers import send_named_notification_email
from tenant_workspace.models import (
    AutoNumberConfiguration,
    AutoNumberSequence,
    OrganizationProfile,
    TenantRole,
    TenantRolePermission,
    TenantUser,
)
from iroad_tenants.models import TenantRegistry

logger = logging.getLogger(__name__)


def _resolve_tenant_favicon_url(request, tenant):
    """Return tenant favicon URL with a stable fallback."""
    company_name = (getattr(tenant, 'company_name', '') or 'iRoad').strip() or 'iRoad'
    default_icon = (
        "https://ui-avatars.com/api/"
        f"?name={quote(company_name)}&background=5051f9&color=fff&size=64&rounded=true&bold=true"
    )
    tenant_registry = _activate_tenant_workspace_schema(request)
    if tenant_registry is None:
        return default_icon
    try:
        profile = OrganizationProfile.objects.order_by('-updated_at', '-created_at').first()
        if profile and getattr(profile, 'logo_file', None):
            try:
                return profile.logo_file.url or default_icon
            except Exception:
                return default_icon
        return default_icon
    except Exception:
        return default_icon
    finally:
        connection.set_schema_to_public()


def _tenant_context_from_session(request):
    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = auth_payload.get('tenant_id')
    tenant_jti = auth_payload.get('jti')
    tenant = None
    if tenant_id:
        tenant = TenantProfile.objects.filter(pk=tenant_id).first()
    if tenant is None:
        _clear_tenant_bootstrap_session(request)
        return None
    if tenant.account_status != 'Active':
        _clear_tenant_bootstrap_session(request)
        return None
    if not tenant_jti:
        _clear_tenant_bootstrap_session(request)
        return None

    # Refresh Redis-backed tenant session on every workspace request so that
    # tenant kill-switch/mass revoke takes effect immediately.
    sec = TenantSecuritySettings.objects.first()
    timeout_minutes = max(60, int(getattr(sec, 'tenant_web_timeout_hours', 12)) * 60)
    if not refresh_tenant_session(str(tenant.tenant_id), str(tenant_jti), timeout_minutes):
        _clear_tenant_bootstrap_session(request)
        return None
    
    # Default to tenant owner profile.
    if tenant.first_name or tenant.last_name:
        display_name = f"{tenant.first_name} {tenant.last_name}".strip()
    else:
        display_name = (tenant.company_name or 'Tenant User').strip()
    display_email = (tenant.primary_email or 'tenant@example.com').strip()
    display_role = 'Tenant Admin'
    permission_forms = set()
    is_tenant_admin = True

    # If this tenant session belongs to a tenant user, override display identity
    # and collect role permissions for menu-level visibility.
    session_data = get_tenant_session(str(tenant.tenant_id), str(tenant_jti)) or {}
    reference_id = str(session_data.get('reference_id') or '').strip()
    if reference_id and reference_id != str(tenant.tenant_id):
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is not None:
            try:
                tenant_user = TenantUser.objects.filter(pk=reference_id).first()
                if tenant_user:
                    display_name = (tenant_user.full_name or tenant_user.username or display_name).strip()
                    display_email = (tenant_user.email or display_email).strip()
                    display_role = (tenant_user.role_name or 'Tenant User').strip()
                    is_tenant_admin = False
                    role = TenantRole.objects.filter(
                        role_name_en__iexact=(tenant_user.role_name or '').strip()
                    ).first()
                    if role:
                        permission_forms = set(
                            TenantRolePermission.objects.filter(
                                role=role,
                                can_view=True,
                            ).values_list('form_name', flat=True)
                        )
            finally:
                connection.set_schema_to_public()

    return {
        'tenant': tenant,
        'display_name': display_name,
        'display_email': display_email,
        'display_role': display_role,
        'tenant_favicon_url': _resolve_tenant_favicon_url(request, tenant),
        'avatar_name': display_name.replace(' ', '+'),
        'is_tenant_admin': is_tenant_admin,
        'perm_forms': permission_forms,
        'can_view_cargo_master': 'Cargo Master' in permission_forms,
        'can_view_booking': 'Booking' in permission_forms,
        'can_view_shipment': 'Shipment' in permission_forms,
        'can_view_sales_invoicing': 'Sales Invoicing' in permission_forms,
    }


def _tenant_redirect(request, route_name):
    tid = str(request.GET.get('tid') or request.POST.get('tid') or '').strip()
    base = reverse(route_name)
    if tid:
        return redirect(f'{base}?tid={tid}')
    return redirect(base)


def _clear_tenant_bootstrap_session(request):
    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = auth_payload.get('tenant_id')
    jti = auth_payload.get('jti')
    if tenant_id and jti:
        revoke_tenant_session_key(str(tenant_id), str(jti))
    # Backward-compat cleanup for older session-based tenant bootstrap keys.
    for key in ('tenant_bootstrap_token', 'tenant_bootstrap_tenant_id', 'tenant_bootstrap_jti', 'tenant_bootstrap_expires_in'):
        request.session.pop(key, None)


def _activate_tenant_workspace_schema(request):
    """Switch DB connection to current tenant schema for tenant workspace ORM."""
    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = auth_payload.get('tenant_id')
    if not tenant_id:
        return None

    connection.set_schema_to_public()
    registry = (
        TenantRegistry.objects.select_related('tenant_profile')
        .filter(tenant_profile_id=tenant_id)
        .first()
    )
    if registry is None:
        return None
    connection.set_tenant(registry)
    return registry


class TenantDashboardView(View):
    """Tenant dashboard rendered from app template copy."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        return render(request, 'iroad_tenants/index.html', context)


class TenantSubscriptionPlanView(View):
    """Tenant subscription plan page (template-only for now)."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        return render(
            request,
            'iroad_tenants/Subscription_Manage/Subscription-plan.html',
            context,
        )


class TenantSubscriptionBillingView(View):
    """Tenant subscription billing page (template-only for now)."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        return render(
            request,
            'iroad_tenants/Subscription_Manage/Subscription-billing.html',
            context,
        )


class TenantRolePermissionChangesView(View):
    """Tenant audit page: role/permission changes (template-only for now)."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        return render(
            request,
            'iroad_tenants/Audit_log/Role--permission-changes.html',
            context,
        )


class TenantCriticalAccountChangesView(View):
    """Tenant audit page: critical account changes (template-only for now)."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        return render(
            request,
            'iroad_tenants/Audit_log/Critical-account-changes.html',
            context,
        )


class TenantLoginSessionEventsView(View):
    """Tenant audit page: login/session events (template-only for now)."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        return render(
            request,
            'iroad_tenants/Audit_log/Login--session-events.html',
            context,
        )


class TenantMyAccountView(View):
    """Tenant self account summary page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        return render(request, 'iroad_tenants/my_account.html', context)

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        tenant = context['tenant']
        
        # Personal Info (Only name and password are now editable)
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        
        # Password Change
        password = request.POST.get('password', '')

        # Password Validation
        if password:
            if len(password) < 8:
                messages.error(request, "Password must be at least 8 characters.", extra_tags='tenant')
                return render(request, 'iroad_tenants/my_account.html', context)

        try:
            # Update Names
            tenant.first_name = first_name
            tenant.last_name = last_name
            
            # Update Password if provided
            if password:
                tenant.portal_bootstrap_password_hash = make_password(password)
            
            tenant.save()
            
            messages.success(request, "Profile updated successfully.", extra_tags='tenant')
            # Refresh context to show new values
            context = _tenant_context_from_session(request)
        except Exception as e:
            messages.error(request, f"Error updating profile: {str(e)}", extra_tags='tenant')

        return render(request, 'iroad_tenants/my_account.html', context)


class TenantAutoNumberConfigurationView(View):
    """Tenant auto number configuration page."""

    ORGANIZATION_FORM_CODE = 'organization-profile'
    ORGANIZATION_FORM_LABEL = 'Organization Profile'
    USERS_FORM_CODE = 'users-administration'
    USERS_FORM_LABEL = 'Users Administration'
    ALLOWED_SEQUENCE_FORMATS = {'numeric', 'alpha', 'alphanumeric'}

    FORM_LABELS = {
        ORGANIZATION_FORM_CODE: ORGANIZATION_FORM_LABEL,
        USERS_FORM_CODE: USERS_FORM_LABEL,
    }

    def _load_config(self, form_code):
        config, _ = AutoNumberConfiguration.objects.get_or_create(
            form_code=form_code,
            defaults={
                'form_label': self.FORM_LABELS.get(form_code, form_code),
                'number_of_digits': 4,
                'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
                'is_unique': True,
            },
        )
        return config

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            requested_form_code = (request.GET.get('form_code') or self.ORGANIZATION_FORM_CODE).strip()
            if requested_form_code not in self.FORM_LABELS:
                requested_form_code = self.ORGANIZATION_FORM_CODE
            config = self._load_config(requested_form_code)
            sequence = AutoNumberSequence.objects.filter(form_code=requested_form_code).first()
            base_next_number = sequence.next_number if sequence else 1
        finally:
            connection.set_schema_to_public()

        context.update(
            {
                'auto_number_config': config,
                'auto_number_form_code': requested_form_code,
                'auto_number_form_label': self.FORM_LABELS.get(requested_form_code, requested_form_code),
                'base_next_number': base_next_number,
                'auto_number_enabled_form_codes': list(self.FORM_LABELS.keys()),
                'tenant_schema_name': tenant_registry.schema_name,
            }
        )
        return render(
            request,
            'iroad_tenants/configuration/Auto-number-configuration.html',
            context,
        )

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        selected_form = (request.POST.get('form_code') or '').strip()
        if selected_form not in self.FORM_LABELS:
            messages.error(
                request,
                'Invalid auto number form selected.',
                extra_tags='tenant',
            )
            return _tenant_redirect(request, 'iroad_tenants:tenant_auto_number_configuration')

        try:
            config = self._load_config(selected_form)
            digits_raw = (request.POST.get('number_of_digits') or '').strip()
            sequence_format = (request.POST.get('sequence_format') or '').strip()

            if not digits_raw.isdigit() or not (1 <= int(digits_raw) <= 10):
                raise ValueError('Number of digits must be between 1 and 10.')
            if sequence_format not in self.ALLOWED_SEQUENCE_FORMATS:
                raise ValueError('Invalid sequence format selected.')

            config.number_of_digits = int(digits_raw)
            config.sequence_format = sequence_format
            config.is_unique = request.POST.get('is_unique') == 'on'
            config.form_label = self.FORM_LABELS[selected_form]
            config.save(update_fields=[
                'number_of_digits',
                'sequence_format',
                'is_unique',
                'form_label',
                'updated_at',
            ])
            messages.success(
                request,
                f'Auto number configuration saved for {self.FORM_LABELS[selected_form]}.',
                extra_tags='tenant',
            )
        except ValueError as exc:
            messages.error(request, str(exc), extra_tags='tenant')
        finally:
            connection.set_schema_to_public()

        return redirect(f"{reverse('iroad_tenants:tenant_auto_number_configuration')}?form_code={selected_form}")


class TenantLogoutView(View):
    """Clear tenant session and redirect to login."""

    def get(self, request):
        self._clear_tenant_session(request)
        response = redirect('login')
        clear_tenant_portal_cookie(response, request=request)
        return response

    def post(self, request):
        self._clear_tenant_session(request)
        response = redirect('login')
        clear_tenant_portal_cookie(response, request=request)
        return response

    @staticmethod
    def _clear_tenant_session(request):
        _clear_tenant_bootstrap_session(request)


class TenantOrganizationProfileView(View):
    """View organization profile."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            profile = _get_or_create_organization_profile(context['tenant'])
            _sync_tenant_ref_if_config_changed(profile)
            owner_label = _owner_user_label(profile.owner_user_id)
            context.update({
                'org': profile,
                'owner_label': owner_label,
                'org_status_label': _organization_status_from_tenant(context['tenant']),
                'logo_display_name': _logo_display_name(profile),
                'tenant_schema_name': tenant_registry.schema_name,
            })
        finally:
            connection.set_schema_to_public()
        return render(request, 'iroad_tenants/Administration/Organization-profile.html', context)


class TenantOrganizationProfileEditView(View):
    """Edit organization profile."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            profile = _get_or_create_organization_profile(context['tenant'])
            _sync_tenant_ref_if_config_changed(profile)
            context.update(_organization_form_context(profile))
            context['org_status_label'] = _organization_status_from_tenant(context['tenant'])
            context['tenant_schema_name'] = tenant_registry.schema_name
        finally:
            connection.set_schema_to_public()
        return render(request, 'iroad_tenants/Administration/Organization-profile-view.html', context)

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            profile = _get_or_create_organization_profile(context['tenant'])
            _sync_tenant_ref_if_config_changed(profile)
            _apply_organization_profile_post(request, profile)
            profile.save()
            messages.success(request, 'Organization profile updated successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_organization_profile')
        except ValueError as exc:
            messages.error(request, str(exc), extra_tags='tenant')
            context.update(_organization_form_context(profile))
            context['org_status_label'] = _organization_status_from_tenant(context['tenant'])
            context['tenant_schema_name'] = tenant_registry.schema_name
            return render(request, 'iroad_tenants/Administration/Organization-profile-view.html', context)
        finally:
            connection.set_schema_to_public()


class TenantUsersAdministrationView(View):
    """Tenant users administration list page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_users = list(
                TenantUser.objects.all().order_by('-created_at', '-updated_at')[:100]
            )
            total_users = len(tenant_users)
            active_users = sum(1 for user in tenant_users if user.status == TenantUser.Status.ACTIVE)
            inactive_users = total_users - active_users
            locked_accounts = sum(1 for user in tenant_users if user.login_attempts >= 3)
            context.update(
                {
                    'tenant_users': tenant_users,
                    'users_total_count': total_users,
                    'users_active_count': active_users,
                    'users_inactive_count': inactive_users,
                    'users_locked_count': locked_accounts,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
        finally:
            connection.set_schema_to_public()
        return render(
            request,
            'iroad_tenants/User_Management/Users-administration.html',
            context,
        )


TENANT_USER_ROLE_OPTIONS = ['Administrator', 'Finance Manager', 'Operations Staff', 'Sales Executive']
TENANT_PERMISSION_MATRIX = [
    {'module_name': 'Master Data', 'form_name': 'Cargo Master'},
    {'module_name': 'Commercial', 'form_name': 'Sales Order'},
    {'module_name': 'Operations', 'form_name': 'Booking'},
    {'module_name': 'Operations', 'form_name': 'Shipment'},
    {'module_name': 'Finance', 'form_name': 'Sales Invoicing'},
    {'module_name': 'Finance', 'form_name': 'Purchase Invoicing'},
]


def _tenant_role_name_options():
    role_names = list(
        TenantRole.objects.order_by('role_name_en').values_list('role_name_en', flat=True)
    )
    if role_names:
        return role_names
    return TENANT_USER_ROLE_OPTIONS


def _tenant_user_login_url(request):
    configured_url = (getattr(settings, 'TENANT_PORTAL_LOGIN_URL', '') or '').strip()
    auth_payload = get_tenant_portal_cookie_payload(request) or {}
    tenant_id = str(auth_payload.get('tenant_id') or '').strip()
    if configured_url:
        if tenant_id and 'tid=' not in configured_url:
            separator = '&' if '?' in configured_url else '?'
            return f'{configured_url}{separator}tid={tenant_id}'
        return configured_url
    login_url = request.build_absolute_uri(reverse('login'))
    if tenant_id:
        login_url = f'{login_url}?tid={tenant_id}'
    return login_url


def _send_tenant_user_welcome_email(*, request, tenant_user, plaintext_password, role_name):
    context_dict = {
        'name': tenant_user.full_name,
        'email': tenant_user.email,
        'password': plaintext_password,
        'role_name': role_name,
        'login_url': _tenant_user_login_url(request),
        'user_name': tenant_user.full_name,
    }
    sent = send_named_notification_email(
        'TENANT_USER_WELCOME',
        recipient_email=tenant_user.email,
        context_dict=context_dict,
        language='en',
        default_subject='Welcome to iRoad - Tenant User Access',
        trigger_source='TemplateName: TENANT_USER_WELCOME',
        force_django_smtp=True,
    )
    if sent:
        return True
    return send_named_notification_email(
        'SUBADMIN_WELCOME',
        recipient_email=tenant_user.email,
        context_dict=context_dict,
        language='en',
        default_subject='Welcome to iRoad - Your Login Credentials',
        trigger_source='TemplateName: SUBADMIN_WELCOME',
        force_django_smtp=True,
    )


def _tenant_user_form_data_from_post(request):
    return {
        'username': (request.POST.get('username') or '').strip(),
        'full_name': (request.POST.get('full_name') or '').strip(),
        'email': (request.POST.get('email') or '').strip().lower(),
        'mobile_country_code': (request.POST.get('mobile_country_code') or '').strip(),
        'mobile_no': (request.POST.get('mobile_no') or '').strip(),
        'status': 'Active' if request.POST.get('status') == 'on' else 'Inactive',
        'roles': request.POST.getlist('roles'),
    }


def _tenant_user_form_data_from_model(tenant_user):
    return {
        'username': tenant_user.username,
        'full_name': tenant_user.full_name,
        'email': tenant_user.email,
        'mobile_country_code': tenant_user.mobile_country_code,
        'mobile_no': tenant_user.mobile_no,
        'status': tenant_user.status,
        'roles': [tenant_user.role_name] if tenant_user.role_name else [],
    }


class TenantUsersAdministrationCreateView(View):
    """Tenant users administration create page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            context.update(
                {
                    'role_options': _tenant_role_name_options(),
                    'form_data': {
                        'mobile_country_code': '',
                        'status': '',
                        'roles': [],
                    },
                    'form_errors': {},
                    'tenant_schema_name': tenant_registry.schema_name,
                    'is_edit_mode': False,
                    'is_view_mode': False,
                }
            )
            return render(
                request,
                'iroad_tenants/User_Management/Users-administration-create.html',
                context,
            )
        finally:
            connection.set_schema_to_public()

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response

        form_data = _tenant_user_form_data_from_post(request)
        password = (request.POST.get('password') or '').strip()
        form_errors = {}

        try:
            role_options = _tenant_role_name_options()
            if not form_data['username']:
                form_errors['username'] = 'Username is required.'
            if not form_data['full_name']:
                form_errors['full_name'] = 'Full Name is required.'
            if not form_data['email']:
                form_errors['email'] = 'Email is required.'
            if not form_data['roles']:
                form_errors['roles'] = 'Select at least one role.'
            else:
                invalid_roles = [role for role in form_data['roles'] if role not in role_options]
                if invalid_roles:
                    form_errors['roles'] = 'Selected role is invalid. Please choose from Roles master.'
            if not password:
                form_errors['password'] = 'Password is required.'
            elif len(password) < 8:
                form_errors['password'] = 'Password must be at least 8 characters.'

            if form_data['username'] and TenantUser.objects.filter(username__iexact=form_data['username']).exists():
                form_errors['username'] = 'This username already exists in this tenant.'
            if form_data['email'] and TenantUser.objects.filter(email__iexact=form_data['email']).exists():
                form_errors['email'] = 'This email already exists in this tenant.'

            if form_errors:
                context.update(
                    {
                        'role_options': role_options,
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'is_edit_mode': False,
                        'is_view_mode': False,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(
                    request,
                    'iroad_tenants/User_Management/Users-administration-create.html',
                    context,
                )

            user_ref_no, account_sequence = _next_auto_number_for_form(
                form_code='users-administration',
                form_label='Users Administration',
                prefix='USR',
            )

            selected_role = form_data['roles'][0] if form_data['roles'] else 'Administrator'
            tenant_user = TenantUser.objects.create(
                tenant_ref_no=user_ref_no,
                account_sequence=account_sequence,
                username=form_data['username'],
                full_name=form_data['full_name'],
                email=form_data['email'],
                mobile_country_code=form_data['mobile_country_code'],
                mobile_no=form_data['mobile_no'],
                password_hash=make_password(password),
                role_name=selected_role,
                status=form_data['status'],
                created_by_label=(context.get('display_name') or '').strip(),
            )
            try:
                email_sent = _send_tenant_user_welcome_email(
                    request=request,
                    tenant_user=tenant_user,
                    plaintext_password=password,
                    role_name=selected_role,
                )
                if email_sent:
                    messages.success(
                        request,
                        'Login credentials email sent to the user.',
                        extra_tags='tenant',
                    )
                else:
                    messages.warning(
                        request,
                        'User created, but no active notification template found for login email.',
                        extra_tags='tenant',
                    )
            except Exception:
                logger.exception(
                    'Tenant user welcome email failed for %s',
                    tenant_user.email,
                )
                messages.warning(
                    request,
                    'User created, but login email could not be sent. Please verify email gateway/template settings.',
                    extra_tags='tenant',
                )
            messages.success(request, 'Tenant user created successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
        finally:
            connection.set_schema_to_public()


class TenantUsersAdministrationEditView(View):
    """Tenant users edit/view page."""

    def get(self, request, user_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_user = TenantUser.objects.filter(pk=user_id).first()
            if tenant_user is None:
                messages.error(request, 'User not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
            is_view_mode = request.GET.get('mode') == 'view'
            role_options = _tenant_role_name_options()
            if tenant_user.role_name and tenant_user.role_name not in role_options:
                role_options = [tenant_user.role_name, *role_options]
            context.update(
                {
                    'role_options': role_options,
                    'form_data': _tenant_user_form_data_from_model(tenant_user),
                    'form_errors': {},
                    'tenant_schema_name': tenant_registry.schema_name,
                    'is_edit_mode': True,
                    'is_view_mode': is_view_mode,
                    'editing_user': tenant_user,
                }
            )
            return render(
                request,
                'iroad_tenants/User_Management/Users-administration-create.html',
                context,
            )
        finally:
            connection.set_schema_to_public()

    def post(self, request, user_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_user = TenantUser.objects.filter(pk=user_id).first()
            if tenant_user is None:
                messages.error(request, 'User not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')

            form_data = _tenant_user_form_data_from_post(request)
            password = (request.POST.get('password') or '').strip()
            form_errors = {}
            role_options = _tenant_role_name_options()
            if tenant_user.role_name and tenant_user.role_name not in role_options:
                role_options = [tenant_user.role_name, *role_options]

            if not form_data['username']:
                form_errors['username'] = 'Username is required.'
            if not form_data['full_name']:
                form_errors['full_name'] = 'Full Name is required.'
            if not form_data['email']:
                form_errors['email'] = 'Email is required.'
            if not form_data['roles']:
                form_errors['roles'] = 'Select at least one role.'
            else:
                invalid_roles = [role for role in form_data['roles'] if role not in role_options]
                if invalid_roles:
                    form_errors['roles'] = 'Selected role is invalid. Please choose from Roles master.'
            if password and len(password) < 8:
                form_errors['password'] = 'Password must be at least 8 characters.'

            if form_data['username'] and TenantUser.objects.filter(username__iexact=form_data['username']).exclude(pk=tenant_user.pk).exists():
                form_errors['username'] = 'This username already exists in this tenant.'
            if form_data['email'] and TenantUser.objects.filter(email__iexact=form_data['email']).exclude(pk=tenant_user.pk).exists():
                form_errors['email'] = 'This email already exists in this tenant.'

            if form_errors:
                context.update(
                    {
                        'role_options': role_options,
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'is_edit_mode': True,
                        'is_view_mode': False,
                        'editing_user': tenant_user,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(
                    request,
                    'iroad_tenants/User_Management/Users-administration-create.html',
                    context,
                )

            tenant_user.username = form_data['username']
            tenant_user.full_name = form_data['full_name']
            tenant_user.email = form_data['email']
            tenant_user.mobile_country_code = form_data['mobile_country_code']
            tenant_user.mobile_no = form_data['mobile_no']
            tenant_user.status = form_data['status']
            tenant_user.role_name = form_data['roles'][0]
            if password:
                tenant_user.password_hash = make_password(password)
            tenant_user.save()

            messages.success(request, 'Tenant user updated successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
        finally:
            connection.set_schema_to_public()


class TenantUsersAdministrationToggleStatusView(View):
    """Activate/deactivate tenant user."""

    def post(self, request, user_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_user = TenantUser.objects.filter(pk=user_id).first()
            if tenant_user is None:
                messages.error(request, 'User not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
            tenant_user.status = (
                TenantUser.Status.INACTIVE
                if tenant_user.status == TenantUser.Status.ACTIVE
                else TenantUser.Status.ACTIVE
            )
            tenant_user.save(update_fields=['status', 'updated_at'])
            messages.success(request, f'User status changed to {tenant_user.status}.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
        finally:
            connection.set_schema_to_public()


class TenantUsersAdministrationDeleteView(View):
    """Delete tenant user from current tenant schema."""

    def post(self, request, user_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_user = TenantUser.objects.filter(pk=user_id).first()
            if tenant_user is None:
                messages.error(request, 'User not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
            tenant_user.delete()
            messages.success(request, 'User deleted successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_users_administration')
        finally:
            connection.set_schema_to_public()


class TenantUsersAdministrationExportView(View):
    """Export current tenant users as CSV."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_users = TenantUser.objects.all().order_by('created_at', 'updated_at')
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="tenant_users_export.csv"'

            writer = csv.writer(response)
            writer.writerow([
                'User Ref No',
                'User ID',
                'Full Name',
                'Email',
                'Username',
                'Role',
                'Status',
                'Last Login',
                'Login Attempts',
                'Created By',
                'Created At',
                'Updated At',
            ])
            for tenant_user in tenant_users:
                writer.writerow([
                    tenant_user.tenant_ref_no,
                    str(tenant_user.user_id),
                    tenant_user.full_name,
                    tenant_user.email,
                    tenant_user.username,
                    tenant_user.role_name,
                    tenant_user.status,
                    tenant_user.last_login_at.isoformat() if tenant_user.last_login_at else '',
                    tenant_user.login_attempts,
                    tenant_user.created_by_label,
                    tenant_user.created_at.isoformat() if tenant_user.created_at else '',
                    tenant_user.updated_at.isoformat() if tenant_user.updated_at else '',
                ])
            return response
        finally:
            connection.set_schema_to_public()


def _tenant_role_form_data_from_post(request):
    return {
        'role_name_en': (request.POST.get('role_name_en') or '').strip(),
        'role_name_ar': (request.POST.get('role_name_ar') or '').strip(),
        'description_en': (request.POST.get('description_en') or '').strip(),
        'description_ar': (request.POST.get('description_ar') or '').strip(),
        'status': 'Active' if request.POST.get('status') == 'on' else 'Inactive',
    }


def _tenant_role_form_data_from_model(role):
    return {
        'role_name_en': role.role_name_en,
        'role_name_ar': role.role_name_ar,
        'description_en': role.description_en,
        'description_ar': role.description_ar,
        'created_by_label': role.created_by_label,
        'status': role.status,
    }


def _permissions_payload_from_post(request):
    rows = []
    for idx, item in enumerate(TENANT_PERMISSION_MATRIX):
        rows.append(
            {
                'module_name': item['module_name'],
                'form_name': item['form_name'],
                'can_view': request.POST.get(f'perm_{idx}_view') == 'on',
                'can_create': request.POST.get(f'perm_{idx}_create') == 'on',
                'can_edit': request.POST.get(f'perm_{idx}_edit') == 'on',
                'can_delete': request.POST.get(f'perm_{idx}_delete') == 'on',
                'can_post': request.POST.get(f'perm_{idx}_post') == 'on',
                'can_approve': request.POST.get(f'perm_{idx}_approve') == 'on',
                'can_export': request.POST.get(f'perm_{idx}_export') == 'on',
                'can_print': request.POST.get(f'perm_{idx}_print') == 'on',
            }
        )
    return rows


def _permissions_by_key(role):
    perms = {}
    for permission in role.permissions.all():
        key = f'{permission.module_name}|{permission.form_name}'
        perms[key] = {
            'can_view': permission.can_view,
            'can_create': permission.can_create,
            'can_edit': permission.can_edit,
            'can_delete': permission.can_delete,
            'can_post': permission.can_post,
            'can_approve': permission.can_approve,
            'can_export': permission.can_export,
            'can_print': permission.can_print,
        }
    return perms


def _permission_matrix_with_values(permission_map=None):
    permission_map = permission_map or {}
    matrix_rows = []
    for item in TENANT_PERMISSION_MATRIX:
        key = f"{item['module_name']}|{item['form_name']}"
        matrix_rows.append(
            {
                'module_name': item['module_name'],
                'form_name': item['form_name'],
                'can_view': permission_map.get(key, {}).get('can_view', False),
                'can_create': permission_map.get(key, {}).get('can_create', False),
                'can_edit': permission_map.get(key, {}).get('can_edit', False),
                'can_delete': permission_map.get(key, {}).get('can_delete', False),
                'can_post': permission_map.get(key, {}).get('can_post', False),
                'can_approve': permission_map.get(key, {}).get('can_approve', False),
                'can_export': permission_map.get(key, {}).get('can_export', False),
                'can_print': permission_map.get(key, {}).get('can_print', False),
            }
        )
    return matrix_rows


class TenantRolesPermissionsView(View):
    """Tenant roles and permissions list page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_roles = list(TenantRole.objects.all().order_by('-created_at', '-updated_at')[:100])
            total_roles = len(tenant_roles)
            active_roles = sum(1 for role in tenant_roles if role.status == TenantRole.Status.ACTIVE)
            inactive_roles = sum(1 for role in tenant_roles if role.status == TenantRole.Status.INACTIVE)
            draft_roles = sum(1 for role in tenant_roles if role.status == TenantRole.Status.DRAFT)
            context.update(
                {
                    'tenant_roles': tenant_roles,
                    'roles_total_count': total_roles,
                    'roles_active_count': active_roles,
                    'roles_inactive_count': inactive_roles,
                    'roles_draft_count': draft_roles,
                    'tenant_schema_name': tenant_registry.schema_name,
                }
            )
        finally:
            connection.set_schema_to_public()
        return render(
            request,
            'iroad_tenants/User_Management/Role/Roles--permissions.html',
            context,
        )


class TenantRolesPermissionsCreateView(View):
    """Tenant role create page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        context.update(
            {
                'form_data': {
                    'status': 'Active',
                    'created_by_label': (context.get('display_name') or '').strip(),
                },
                'form_errors': {},
                'permission_matrix': _permission_matrix_with_values(),
                'is_edit_mode': False,
                'is_view_mode': False,
            }
        )
        return render(
            request,
            'iroad_tenants/User_Management/Role/Roles-permissions-Create.html',
            context,
        )

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        form_data = _tenant_role_form_data_from_post(request)
        form_data['created_by_label'] = (context.get('display_name') or '').strip()
        permissions_payload = _permissions_payload_from_post(request)
        form_errors = {}
        try:
            if not form_data['role_name_en']:
                form_errors['role_name_en'] = 'Role name in English is required.'
            if not form_data['role_name_ar']:
                form_errors['role_name_ar'] = 'Role name in Arabic is required.'
            if form_data['role_name_en'] and TenantRole.objects.filter(
                role_name_en__iexact=form_data['role_name_en']
            ).exists():
                form_errors['role_name_en'] = 'This role name already exists in this tenant.'
            if form_data['role_name_ar'] and TenantRole.objects.filter(
                role_name_ar__iexact=form_data['role_name_ar']
            ).exists():
                form_errors['role_name_ar'] = 'This Arabic role name already exists in this tenant.'

            if form_errors:
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'permission_matrix': permissions_payload,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'is_edit_mode': False,
                        'is_view_mode': False,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(
                    request,
                    'iroad_tenants/User_Management/Role/Roles-permissions-Create.html',
                    context,
                )

            tenant_role = TenantRole.objects.create(
                role_name_en=form_data['role_name_en'],
                role_name_ar=form_data['role_name_ar'],
                description_en=form_data['description_en'],
                description_ar=form_data['description_ar'],
                status=form_data['status'],
                created_by_label=(context.get('display_name') or '').strip(),
            )
            TenantRolePermission.objects.bulk_create(
                [
                    TenantRolePermission(
                        role=tenant_role,
                        module_name=item['module_name'],
                        form_name=item['form_name'],
                        can_view=item['can_view'],
                        can_create=item['can_create'],
                        can_edit=item['can_edit'],
                        can_delete=item['can_delete'],
                        can_post=item['can_post'],
                        can_approve=item['can_approve'],
                        can_export=item['can_export'],
                        can_print=item['can_print'],
                    )
                    for item in permissions_payload
                ]
            )
            messages.success(request, 'Role created successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
        finally:
            connection.set_schema_to_public()


class TenantRolesPermissionsEditView(View):
    """Tenant role edit/view page."""

    def get(self, request, role_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_role = TenantRole.objects.filter(pk=role_id).prefetch_related('permissions').first()
            if tenant_role is None:
                messages.error(request, 'Role not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
            is_view_mode = request.GET.get('mode') == 'view'
            context.update(
                {
                    'form_data': {
                        **_tenant_role_form_data_from_model(tenant_role),
                        'created_by_label': (context.get('display_name') or '').strip(),
                    },
                    'form_errors': {},
                    'permission_matrix': _permission_matrix_with_values(_permissions_by_key(tenant_role)),
                    'tenant_schema_name': tenant_registry.schema_name,
                    'is_edit_mode': True,
                    'is_view_mode': is_view_mode,
                    'editing_role': tenant_role,
                }
            )
            return render(
                request,
                'iroad_tenants/User_Management/Role/Roles-permissions-Create.html',
                context,
            )
        finally:
            connection.set_schema_to_public()

    def post(self, request, role_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        form_data = _tenant_role_form_data_from_post(request)
        form_data['created_by_label'] = (context.get('display_name') or '').strip()
        permissions_payload = _permissions_payload_from_post(request)
        form_errors = {}
        try:
            tenant_role = TenantRole.objects.filter(pk=role_id).first()
            if tenant_role is None:
                messages.error(request, 'Role not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')

            if not form_data['role_name_en']:
                form_errors['role_name_en'] = 'Role name in English is required.'
            if not form_data['role_name_ar']:
                form_errors['role_name_ar'] = 'Role name in Arabic is required.'
            if form_data['role_name_en'] and TenantRole.objects.filter(
                role_name_en__iexact=form_data['role_name_en']
            ).exclude(pk=tenant_role.pk).exists():
                form_errors['role_name_en'] = 'This role name already exists in this tenant.'
            if form_data['role_name_ar'] and TenantRole.objects.filter(
                role_name_ar__iexact=form_data['role_name_ar']
            ).exclude(pk=tenant_role.pk).exists():
                form_errors['role_name_ar'] = 'This Arabic role name already exists in this tenant.'

            if form_errors:
                context.update(
                    {
                        'form_data': form_data,
                        'form_errors': form_errors,
                        'permission_matrix': permissions_payload,
                        'tenant_schema_name': tenant_registry.schema_name,
                        'is_edit_mode': True,
                        'is_view_mode': False,
                        'editing_role': tenant_role,
                    }
                )
                messages.error(request, 'Please fix the highlighted errors.', extra_tags='tenant')
                return render(
                    request,
                    'iroad_tenants/User_Management/Role/Roles-permissions-Create.html',
                    context,
                )

            tenant_role.role_name_en = form_data['role_name_en']
            tenant_role.role_name_ar = form_data['role_name_ar']
            tenant_role.description_en = form_data['description_en']
            tenant_role.description_ar = form_data['description_ar']
            tenant_role.status = form_data['status']
            tenant_role.created_by_label = (context.get('display_name') or '').strip()
            tenant_role.save()

            TenantRolePermission.objects.filter(role=tenant_role).delete()
            TenantRolePermission.objects.bulk_create(
                [
                    TenantRolePermission(
                        role=tenant_role,
                        module_name=item['module_name'],
                        form_name=item['form_name'],
                        can_view=item['can_view'],
                        can_create=item['can_create'],
                        can_edit=item['can_edit'],
                        can_delete=item['can_delete'],
                        can_post=item['can_post'],
                        can_approve=item['can_approve'],
                        can_export=item['can_export'],
                        can_print=item['can_print'],
                    )
                    for item in permissions_payload
                ]
            )
            messages.success(request, 'Role updated successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
        finally:
            connection.set_schema_to_public()


class TenantRolesPermissionsToggleStatusView(View):
    """Activate/deactivate tenant role."""

    def post(self, request, role_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_role = TenantRole.objects.filter(pk=role_id).first()
            if tenant_role is None:
                messages.error(request, 'Role not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
            tenant_role.status = (
                TenantRole.Status.INACTIVE
                if tenant_role.status == TenantRole.Status.ACTIVE
                else TenantRole.Status.ACTIVE
            )
            tenant_role.save(update_fields=['status', 'updated_at'])
            messages.success(request, f'Role status changed to {tenant_role.status}.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
        finally:
            connection.set_schema_to_public()


class TenantRolesPermissionsDeleteView(View):
    """Delete tenant role from current tenant schema."""

    def post(self, request, role_id):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_role = TenantRole.objects.filter(pk=role_id).first()
            if tenant_role is None:
                messages.error(request, 'Role not found.', extra_tags='tenant')
                return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
            tenant_role.delete()
            messages.success(request, 'Role deleted successfully.', extra_tags='tenant')
            return _tenant_redirect(request, 'iroad_tenants:tenant_roles_permissions')
        finally:
            connection.set_schema_to_public()


class TenantRolesPermissionsExportView(View):
    """Export current tenant roles as CSV."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response, request=request)
            return response
        try:
            tenant_roles = TenantRole.objects.all().order_by('created_at', 'updated_at')
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="tenant_roles_export.csv"'

            writer = csv.writer(response)
            writer.writerow(
                [
                    'Role ID',
                    'Role Name (English)',
                    'Role Name (Arabic)',
                    'Description (English)',
                    'Description (Arabic)',
                    'Status',
                    'Created By',
                    'Created At',
                    'Updated At',
                ]
            )
            for tenant_role in tenant_roles:
                writer.writerow(
                    [
                        str(tenant_role.role_id),
                        tenant_role.role_name_en,
                        tenant_role.role_name_ar,
                        tenant_role.description_en,
                        tenant_role.description_ar,
                        tenant_role.status,
                        tenant_role.created_by_label,
                        tenant_role.created_at.isoformat() if tenant_role.created_at else '',
                        tenant_role.updated_at.isoformat() if tenant_role.updated_at else '',
                    ]
                )
            return response
        finally:
            connection.set_schema_to_public()


def _organization_form_context(profile):
    selected_timezone = (profile.timezone or 'Asia/Riyadh').strip() or 'Asia/Riyadh'
    return {
        'org': profile,
        'owner_label': _owner_user_label(profile.owner_user_id),
        'logo_display_name': _logo_display_name(profile),
        'countries': list(
            Country.objects.filter(is_active=True).order_by('name_en').values(
                'country_code',
                'name_en',
            ),
        ),
        'currencies': list(
            Currency.objects.filter(is_active=True).order_by('currency_code').values(
                'currency_code',
                'name_en',
            ),
        ),
        'date_format_choices': OrganizationProfile.DATE_FORMAT_CHOICES,
        'number_format_choices': OrganizationProfile.NUMBER_FORMAT_CHOICES,
        'negative_format_choices': OrganizationProfile.NEGATIVE_FORMAT_CHOICES,
        'language_choices': OrganizationProfile.SYSTEM_LANGUAGE_CHOICES,
        'selected_timezone': selected_timezone,
        'timezone_choices': [
            'Asia/Riyadh',
            'UTC',
            'Asia/Dubai',
            'Europe/London',
        ],
        'org_status_label': 'Active',
    }


def _owner_user_label(owner_user_id):
    if not owner_user_id:
        return 'N/A'
    # In tenant workspace, owner_user_id is seeded from signup tenant profile id.
    tenant_owner = TenantProfile.objects.filter(pk=owner_user_id).first()
    if tenant_owner:
        tenant_name = (
            f"{(tenant_owner.first_name or '').strip()} {(tenant_owner.last_name or '').strip()}"
        ).strip()
        if tenant_name:
            return tenant_name
        return (tenant_owner.company_name or tenant_owner.primary_email or 'N/A').strip()

    # Fallback: support admin user ids if used by future migrations.
    owner = AdminUser.objects.filter(pk=owner_user_id).first()
    if owner:
        label = f'{owner.first_name} {owner.last_name}'.strip()
        return label or owner.email
    return 'N/A'


def _logo_display_name(profile):
    if not getattr(profile, 'logo_file', None):
        return ''
    return os.path.basename(profile.logo_file.name or '')


def _organization_status_from_tenant(tenant):
    """Map superadmin account status to Organization Profile read-only status."""
    status = (getattr(tenant, 'account_status', '') or '').strip()
    if status == 'Active':
        return 'Active'
    if status.startswith('Suspended_'):
        return 'Suspended'
    # Keep UI constrained to the documented values.
    return 'Suspended'


def _get_or_create_organization_profile(tenant):
    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code='organization-profile',
        defaults={
            'form_label': 'Organization Profile',
            'number_of_digits': 4,
            'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
            'is_unique': True,
        },
    )
    # Use a deterministic "active" record in case historical duplicates exist.
    profile = (
        OrganizationProfile.objects.order_by('-updated_at', '-created_at').first()
    )
    if profile:
        if not profile.owner_user_id:
            profile.owner_user_id = str(tenant.pk)
            profile.save(update_fields=['owner_user_id', 'updated_at'])
        return profile

    seq, _ = AutoNumberSequence.objects.get_or_create(
        form_code='organization-profile',
        defaults={'next_number': 1},
    )
    account_sequence = seq.next_number
    ref_no = _render_tenant_ref_no(account_sequence, config, prefix='ORG')

    default_currency = (
        Currency.objects.filter(is_active=True).order_by('currency_code').first()
    )
    default_country = (
        Country.objects.filter(is_active=True).order_by('name_en').first()
    )

    profile = OrganizationProfile.objects.create(
        tenant_ref_no=ref_no,
        account_sequence=account_sequence,
        owner_user_id=str(tenant.pk),
        name_ar=tenant.company_name or '',
        name_en=tenant.company_name or '',
        cr_number=tenant.registration_number or '',
        tax_number=tenant.tax_number or '',
        primary_email=tenant.primary_email or '',
        primary_mobile=tenant.primary_phone or '',
        country_code=(default_country.country_code if default_country else ''),
        base_currency_code=(default_currency.currency_code if default_currency else ''),
        timezone='Asia/Riyadh',
    )
    seq.next_number = account_sequence + 1
    seq.save(update_fields=['next_number', 'updated_at'])
    return profile


def _sync_tenant_ref_if_config_changed(profile):
    config = AutoNumberConfiguration.objects.filter(
        form_code='organization-profile',
    ).first()
    if not config:
        return
    expected = _render_tenant_ref_no(profile.account_sequence, config, prefix='ORG')
    if profile.tenant_ref_no != expected:
        profile.tenant_ref_no = expected
        profile.save(update_fields=['tenant_ref_no', 'updated_at'])


def _render_tenant_ref_no(sequence, config, prefix='ORG'):
    n = int(sequence or 1)
    digits = max(1, int(config.number_of_digits or 4))
    if config.sequence_format == AutoNumberConfiguration.SequenceFormat.ALPHA:
        rendered = _int_to_alpha(n)
    elif config.sequence_format == AutoNumberConfiguration.SequenceFormat.ALPHANUMERIC:
        rendered = f'A{str(n).zfill(digits)}'
    else:
        rendered = str(n).zfill(digits)
    return f'{prefix}-{rendered}'


def _next_auto_number_for_form(form_code, form_label, prefix):
    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code=form_code,
        defaults={
            'form_label': form_label,
            'number_of_digits': 4,
            'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
            'is_unique': True,
        },
    )
    sequence, _ = AutoNumberSequence.objects.get_or_create(
        form_code=form_code,
        defaults={'next_number': 1},
    )
    account_sequence = int(sequence.next_number or 1)
    ref_no = _render_tenant_ref_no(account_sequence, config, prefix=prefix)
    sequence.next_number = account_sequence + 1
    sequence.save(update_fields=['next_number', 'updated_at'])
    return ref_no, account_sequence


def _int_to_alpha(value):
    num = max(1, int(value))
    chars = []
    while num > 0:
        num, rem = divmod(num - 1, 26)
        chars.append(chr(65 + rem))
    return ''.join(reversed(chars))


def _apply_organization_profile_post(request, profile):
    post = request.POST
    name_ar = (post.get('name_ar') or '').strip()
    name_en = (post.get('name_en') or '').strip()
    cr_number = (post.get('cr_number') or '').strip()
    tax_number = (post.get('tax_number') or '').strip()
    country_code = (post.get('country_code') or '').strip().upper()
    city = (post.get('city') or '').strip()
    street = (post.get('street') or '').strip()
    address_line_1 = (post.get('address_line_1') or '').strip()
    primary_email = (post.get('primary_email') or '').strip()
    primary_mobile = (post.get('primary_mobile') or '').strip()

    # Preserve existing required values when user updates only a subset
    # (e.g. uploading logo), instead of wiping them to empty strings.
    profile.name_ar = name_ar or profile.name_ar
    profile.name_en = name_en or profile.name_en
    profile.cr_number = cr_number or profile.cr_number
    profile.tax_number = tax_number or profile.tax_number
    profile.country_code = country_code or profile.country_code
    profile.city = city or profile.city
    profile.district = (post.get('district') or '').strip()
    profile.street = street or profile.street
    profile.building_no = (post.get('building_no') or '').strip()
    profile.postal_code = (post.get('postal_code') or '').strip()
    profile.address_line_1 = address_line_1 or profile.address_line_1
    profile.address_line_2 = (post.get('address_line_2') or '').strip()
    profile.primary_email = primary_email or profile.primary_email
    profile.primary_mobile = primary_mobile or profile.primary_mobile
    profile.website = (post.get('website') or '').strip()
    if 'secondary_currency_code' in post:
        profile.secondary_currency_code = (post.get('secondary_currency_code') or '').strip().upper()
    if 'support_email' in post:
        profile.support_email = (post.get('support_email') or '').strip()
    if 'support_mobile_1' in post:
        profile.support_mobile_1 = (post.get('support_mobile_1') or '').strip()
    if 'support_mobile_2' in post:
        profile.support_mobile_2 = (post.get('support_mobile_2') or '').strip()
    if 'driver_instructions' in post:
        profile.driver_instructions = (post.get('driver_instructions') or '').strip()
    profile.system_language = (post.get('system_language') or 'en').strip()
    profile.timezone = (post.get('timezone') or 'Asia/Riyadh').strip()
    profile.date_format = (post.get('date_format') or 'DD/MM/YYYY').strip()
    profile.number_format = (post.get('number_format') or '1,234.56').strip()
    profile.negative_format = (post.get('negative_format') or '-100').strip()

    new_base_currency = (post.get('base_currency_code') or '').strip().upper()
    if profile.base_currency_code and new_base_currency and new_base_currency != profile.base_currency_code:
        raise ValueError('Base Currency is immutable after initial setup.')
    if not profile.base_currency_code:
        profile.base_currency_code = new_base_currency

    logo_file = request.FILES.get('logo_file')
    clear_logo = (post.get('clear_logo') or '').strip() == '1'
    if clear_logo:
        if profile.logo_file:
            profile.logo_file.delete(save=False)
        profile.logo_file = None
    if logo_file:
        ext = os.path.splitext(logo_file.name or '')[1].lower() or '.png'
        logo_file.name = f'org_{profile.id}_{uuid.uuid4().hex[:10]}{ext}'
        profile.logo_file = logo_file

    # Keep updates resilient for partially-initialized legacy records:
    # allow partial saves (e.g. logo upload) while still validating
    # critical format rules when values are provided.
    if profile.cr_number and not profile.cr_number.isdigit():
        raise ValueError('CR Number must be numeric.')
