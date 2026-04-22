from django.shortcuts import redirect, render
from django.views import View
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db import connection
from superadmin.models import TenantProfile
from superadmin.redis_helpers import revoke_tenant_session_key
from tenant_workspace.models import AutoNumberConfiguration
from iroad_tenants.models import TenantRegistry


def _tenant_context_from_session(request):
    tenant_id = request.session.get('tenant_bootstrap_tenant_id')
    tenant = None
    if tenant_id:
        tenant = TenantProfile.objects.filter(pk=tenant_id).first()
    if tenant is None:
        return None
    
    # Use First Name + Last Name if available, otherwise Company Name
    if tenant.first_name or tenant.last_name:
        display_name = f"{tenant.first_name} {tenant.last_name}".strip()
    else:
        display_name = (tenant.company_name or 'Tenant User').strip()
        
    display_email = (tenant.primary_email or 'tenant@example.com').strip()
    return {
        'tenant': tenant,
        'display_name': display_name,
        'display_email': display_email,
        'display_role': 'Tenant Admin',
        'avatar_name': display_name.replace(' ', '+'),
    }


def _activate_tenant_workspace_schema(request):
    """Switch DB connection to current tenant schema for tenant workspace ORM."""
    tenant_id = request.session.get('tenant_bootstrap_tenant_id')
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
            return redirect('login')
        return render(request, 'iroad_tenants/index.html', context)


class TenantMyAccountView(View):
    """Tenant self account summary page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            return redirect('login')
        return render(request, 'iroad_tenants/my_account.html', context)

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            return redirect('login')

        tenant = context['tenant']
        
        # Personal Info (Only name and password are now editable)
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        
        # Password Change
        password = request.POST.get('password', '')

        # Password Validation
        if password:
            if len(password) < 8:
                messages.error(request, "Password must be at least 8 characters.")
                return render(request, 'iroad_tenants/my_account.html', context)

        try:
            # Update Names
            tenant.first_name = first_name
            tenant.last_name = last_name
            
            # Update Password if provided
            if password:
                tenant.portal_bootstrap_password_hash = make_password(password)
            
            tenant.save()
            
            messages.success(request, "Profile updated successfully.")
            # Refresh context to show new values
            context = _tenant_context_from_session(request)
        except Exception as e:
            messages.error(request, f"Error updating profile: {str(e)}")

        return render(request, 'iroad_tenants/my_account.html', context)


class TenantAutoNumberConfigurationView(View):
    """Tenant auto number configuration page."""

    ORGANIZATION_FORM_CODE = 'organization-profile'
    ORGANIZATION_FORM_LABEL = 'Organization Profile'
    ALLOWED_SEQUENCE_FORMATS = {'numeric', 'alpha', 'alphanumeric'}

    def _load_organization_config(self):
        config, _ = AutoNumberConfiguration.objects.get_or_create(
            form_code=self.ORGANIZATION_FORM_CODE,
            defaults={
                'form_label': self.ORGANIZATION_FORM_LABEL,
                'number_of_digits': 4,
                'sequence_format': AutoNumberConfiguration.SequenceFormat.NUMERIC,
                'is_unique': True,
            },
        )
        return config

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            return redirect('login')
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            return redirect('login')
        try:
            config = self._load_organization_config()
        finally:
            connection.set_schema_to_public()

        context.update(
            {
                'auto_number_config': config,
                'auto_number_form_code': self.ORGANIZATION_FORM_CODE,
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
            return redirect('login')
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            return redirect('login')

        selected_form = (request.POST.get('form_code') or '').strip()
        if selected_form != self.ORGANIZATION_FORM_CODE:
            messages.error(
                request,
                'Auto number backend is currently enabled only for Organization Profile.',
            )
            return redirect('iroad_tenants:tenant_auto_number_configuration')

        try:
            config = self._load_organization_config()
            digits_raw = (request.POST.get('number_of_digits') or '').strip()
            sequence_format = (request.POST.get('sequence_format') or '').strip()

            if not digits_raw.isdigit() or not (1 <= int(digits_raw) <= 10):
                raise ValueError('Number of digits must be between 1 and 10.')
            if sequence_format not in self.ALLOWED_SEQUENCE_FORMATS:
                raise ValueError('Invalid sequence format selected.')

            config.number_of_digits = int(digits_raw)
            config.sequence_format = sequence_format
            config.is_unique = request.POST.get('is_unique') == 'on'
            config.form_label = self.ORGANIZATION_FORM_LABEL
            config.save(update_fields=[
                'number_of_digits',
                'sequence_format',
                'is_unique',
                'form_label',
                'updated_at',
            ])
            messages.success(
                request,
                f'Auto number configuration saved for {self.ORGANIZATION_FORM_LABEL}.',
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        finally:
            connection.set_schema_to_public()

        return redirect('iroad_tenants:tenant_auto_number_configuration')


class TenantLogoutView(View):
    """Clear tenant session and redirect to login."""

    def get(self, request):
        self._clear_tenant_session(request)
        return redirect('login')

    def post(self, request):
        self._clear_tenant_session(request)
        return redirect('login')

    @staticmethod
    def _clear_tenant_session(request):
        tenant_id = request.session.get('tenant_bootstrap_tenant_id')
        jti = request.session.get('tenant_bootstrap_jti')
        if tenant_id and jti:
            revoke_tenant_session_key(str(tenant_id), str(jti))
        for key in (
            'tenant_bootstrap_token',
            'tenant_bootstrap_tenant_id',
            'tenant_bootstrap_jti',
            'tenant_bootstrap_expires_in',
        ):
            request.session.pop(key, None)
