from django.shortcuts import redirect, render
from django.views import View
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db import connection
from django.utils import timezone
from superadmin.models import TenantProfile, TenantSecuritySettings
from superadmin.models import AdminUser, Country, Currency
from superadmin.redis_helpers import (
    refresh_tenant_session,
    revoke_tenant_session_key,
)
from superadmin.tenant_portal_auth import (
    clear_tenant_portal_cookie,
    get_tenant_portal_cookie_payload,
)
from tenant_workspace.models import (
    AutoNumberConfiguration,
    AutoNumberSequence,
    OrganizationProfile,
)
from iroad_tenants.models import TenantRegistry


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
            clear_tenant_portal_cookie(response)
            return response
        return render(request, 'iroad_tenants/index.html', context)


class TenantMyAccountView(View):
    """Tenant self account summary page."""

    def get(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response)
            return response
        return render(request, 'iroad_tenants/my_account.html', context)

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response)
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
            response = redirect('login')
            clear_tenant_portal_cookie(response)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response)
            return response
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
            response = redirect('login')
            clear_tenant_portal_cookie(response)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response)
            return response

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
        response = redirect('login')
        clear_tenant_portal_cookie(response)
        return response

    def post(self, request):
        self._clear_tenant_session(request)
        response = redirect('login')
        clear_tenant_portal_cookie(response)
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
            clear_tenant_portal_cookie(response)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response)
            return response
        try:
            profile = _get_or_create_organization_profile(context['tenant'])
            _sync_tenant_ref_if_config_changed(profile)
            owner_label = _owner_user_label(profile.owner_user_id)
            context.update({
                'org': profile,
                'owner_label': owner_label,
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
            clear_tenant_portal_cookie(response)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response)
            return response
        try:
            profile = _get_or_create_organization_profile(context['tenant'])
            _sync_tenant_ref_if_config_changed(profile)
            context.update(_organization_form_context(profile))
            context['tenant_schema_name'] = tenant_registry.schema_name
        finally:
            connection.set_schema_to_public()
        return render(request, 'iroad_tenants/Administration/Organization-profile-view.html', context)

    def post(self, request):
        context = _tenant_context_from_session(request)
        if context is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response)
            return response
        tenant_registry = _activate_tenant_workspace_schema(request)
        if tenant_registry is None:
            response = redirect('login')
            clear_tenant_portal_cookie(response)
            return response
        try:
            profile = _get_or_create_organization_profile(context['tenant'])
            _sync_tenant_ref_if_config_changed(profile)
            _apply_organization_profile_post(request, profile)
            profile.save()
            messages.success(request, 'Organization profile updated successfully.')
            return redirect('iroad_tenants:tenant_organization_profile')
        except ValueError as exc:
            messages.error(request, str(exc))
            context.update(_organization_form_context(profile))
            context['tenant_schema_name'] = tenant_registry.schema_name
            return render(request, 'iroad_tenants/Administration/Organization-profile-view.html', context)
        finally:
            connection.set_schema_to_public()


def _organization_form_context(profile):
    return {
        'org': profile,
        'owner_label': _owner_user_label(profile.owner_user_id),
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
        'timezone_choices': [
            'Asia/Riyadh',
            'UTC',
            'Asia/Dubai',
            'Europe/London',
        ],
    }


def _owner_user_label(owner_user_id):
    if not owner_user_id:
        return 'N/A'
    owner = AdminUser.objects.filter(pk=owner_user_id).first()
    if not owner:
        return 'N/A'
    label = f'{owner.first_name} {owner.last_name}'.strip()
    return label or owner.email


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
    profile = OrganizationProfile.objects.first()
    if profile:
        return profile

    seq, _ = AutoNumberSequence.objects.get_or_create(
        form_code='organization-profile',
        defaults={'next_number': 1},
    )
    account_sequence = seq.next_number
    ref_no = _render_tenant_ref_no(account_sequence, config)

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
    expected = _render_tenant_ref_no(profile.account_sequence, config)
    if profile.tenant_ref_no != expected:
        profile.tenant_ref_no = expected
        profile.save(update_fields=['tenant_ref_no', 'updated_at'])


def _render_tenant_ref_no(sequence, config):
    n = int(sequence or 1)
    digits = max(1, int(config.number_of_digits or 4))
    if config.sequence_format == AutoNumberConfiguration.SequenceFormat.ALPHA:
        rendered = _int_to_alpha(n)
    elif config.sequence_format == AutoNumberConfiguration.SequenceFormat.ALPHANUMERIC:
        rendered = f'A{str(n).zfill(digits)}'
    else:
        rendered = str(n).zfill(digits)
    return f'ORG-{rendered}'


def _int_to_alpha(value):
    num = max(1, int(value))
    chars = []
    while num > 0:
        num, rem = divmod(num - 1, 26)
        chars.append(chr(65 + rem))
    return ''.join(reversed(chars))


def _apply_organization_profile_post(request, profile):
    post = request.POST
    profile.name_ar = (post.get('name_ar') or '').strip()
    profile.name_en = (post.get('name_en') or '').strip()
    profile.cr_number = (post.get('cr_number') or '').strip()
    profile.tax_number = (post.get('tax_number') or '').strip()
    profile.country_code = (post.get('country_code') or '').strip().upper()
    profile.city = (post.get('city') or '').strip()
    profile.district = (post.get('district') or '').strip()
    profile.street = (post.get('street') or '').strip()
    profile.building_no = (post.get('building_no') or '').strip()
    profile.postal_code = (post.get('postal_code') or '').strip()
    profile.address_line_1 = (post.get('address_line_1') or '').strip()
    profile.address_line_2 = (post.get('address_line_2') or '').strip()
    profile.primary_email = (post.get('primary_email') or '').strip()
    profile.primary_mobile = (post.get('primary_mobile') or '').strip()
    profile.website = (post.get('website') or '').strip()
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
    if logo_file:
        profile.logo_file = logo_file

    if not profile.name_ar or not profile.name_en:
        raise ValueError('Organization Name (AR) and (EN) are required.')
    if not profile.cr_number.isdigit():
        raise ValueError('CR Number must be numeric.')
    if not profile.tax_number:
        raise ValueError('VAT Number is required.')
    if not profile.primary_email:
        raise ValueError('Official Email is required.')
    if not profile.primary_mobile:
        raise ValueError('Mobile is required.')
    if not profile.country_code:
        raise ValueError('Country is required.')
    if not profile.city:
        raise ValueError('City is required.')
    if not profile.street:
        raise ValueError('Street is required.')
    if not profile.address_line_1:
        raise ValueError('Address Line 1 is required.')
    if not profile.base_currency_code:
        raise ValueError('Base Currency is required.')
