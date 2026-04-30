import re

from django import forms
from django.core.exceptions import ValidationError
import pytz

from .models import (
    AdminSecuritySettings,
    AddOnsPricingPolicy,
    AdminUser,
    BaseCurrencyConfig,
    BankAccount,
    CommGateway,
    CommLog,
    Country,
    Currency,
    EventMapping,
    ExchangeRate,
    GeneralTaxSettings,
    GlobalSystemRules,
    InternalAlertRoute,
    LegalIdentity,
    NotificationTemplate,
    PaymentGateway,
    PaymentMethod,
    PlanPricingCycle,
    PromoCode,
    Role,
    SubscriptionFAQ,
    PushNotification,
    SupportCategory,
    SupportTicket,
    SubscriptionPlan,
    SystemBanner,
    TaxCode,
    TenantProfile,
    TenantSecuritySettings,
    TicketReply,
    CannedResponse,
)


def apply_premium_styling(form):
    """
    Utility to inject premium Bootstrap classes into Django form widgets.
    """
    for field_name, field in form.fields.items():
        widget = field.widget
        widget_name = widget.__class__.__name__

        # Inputs and selects
        if widget_name in [
            'TextInput', 'EmailInput', 'PasswordInput', 'NumberInput', 
            'Textarea', 'Select', 'DateInput', 'DateTimeInput', 'URLInput',
            'ClearableFileInput'
        ]:
            existing_classes = widget.attrs.get('class', '')
            target_class = 'form-select' if widget_name == 'Select' else 'form-control'
            if target_class not in existing_classes:
                widget.attrs['class'] = f"{existing_classes} {target_class}".strip()

        # Checkboxes
        if widget_name == 'CheckboxInput':
            existing_classes = widget.attrs.get('class', '')
            if 'form-check-input' not in existing_classes:
                widget.attrs['class'] = f"{existing_classes} form-check-input".strip()


class LoginForm(forms.Form):
    email = forms.EmailField(max_length=100)
    password = forms.CharField(widget=forms.PasswordInput)


class OTPVerificationForm(forms.Form):
    otp = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(
            attrs={
                'class': 'auth-input',
                'id': 'otp',
                'placeholder': 'Enter 6-digit code',
                'autocomplete': 'one-time-code',
                'inputmode': 'numeric',
                'pattern': r'\d{6}',
            }
        ),
    )

    def clean_otp(self):
        otp = (self.cleaned_data.get('otp') or '').strip()
        if not otp.isdigit():
            raise ValidationError('OTP must contain digits only.')
        if len(otp) != 6:
            raise ValidationError('OTP must be exactly 6 digits.')
        return otp


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        max_length=100,
        widget=forms.EmailInput(
            attrs={
                'class': 'auth-input',
                'id': 'email',
                'placeholder': 'Enter your registered email',
                'autocomplete': 'email',
            }
        ),
    )


class SetPasswordForm(forms.Form):
    password = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(
            attrs={
                'autocomplete': 'new-password',
                'class': 'auth-input',
                'id': 'id_password',
            }
        ),
    )
    password_confirm = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(
            attrs={
                'autocomplete': 'new-password',
                'class': 'auth-input',
                'id': 'id_password_confirm',
            }
        ),
    )

    def clean_password(self):
        password = self.cleaned_data.get('password') or ''
        if len(password) < 8:
            raise ValidationError('Password must be at least 8 characters.')
        if not re.search(r'[a-z]', password):
            raise ValidationError('Password must include a lowercase letter.')
        if not re.search(r'[A-Z]', password):
            raise ValidationError('Password must include an uppercase letter.')
        if not re.search(r'\d', password):
            raise ValidationError('Password must include a number.')
        if not re.search(r'[^A-Za-z0-9]', password):
            raise ValidationError('Password must include a special character.')
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password')
        p2 = cleaned.get('password_confirm')
        if p1 and p2 and p1 != p2:
            raise ValidationError('Passwords do not match.')
        return cleaned

class RoleForm(forms.ModelForm):
    """Status is edited via a boolean toggle (Active ↔ Inactive) in templates."""

    status_active = forms.BooleanField(
        required=False,
        label='',
        widget=forms.CheckboxInput(
            attrs={
                'class': 'form-check-input',
                'role': 'switch',
                'id': 'id_role_status_active',
            }
        ),
    )

    class Meta:
        model = Role
        fields = ['role_name_en', 'role_name_ar', 'description']

    def clean_role_name_en(self):
        value = self.cleaned_data.get('role_name_en', '').strip()
        qs = Role.objects.filter(role_name_en=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Role name (EN) must be unique.')
        return value

    def clean_role_name_ar(self):
        value = self.cleaned_data.get('role_name_ar', '').strip()
        qs = Role.objects.filter(role_name_ar=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Role name (AR) must be unique.')
        return value

    def clean(self):
        cleaned_data = super().clean()

        # Backend-only rule: system default roles cannot be modified via UI.
        if self.instance and self.instance.pk and self.instance.is_system_default:
            raise ValidationError('System default roles cannot be modified')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.status = (
            'Active' if self.cleaned_data.get('status_active') else 'Inactive'
        )
        if commit:
            instance.save()
        return instance

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial['status_active'] = self.instance.status == 'Active'
        else:
            self.initial.setdefault('status_active', True)

        apply_premium_styling(self)

        # DesignerDesign-compatible field styling classes.
        # (Template layer must not use `as_widget(attrs={...})` to avoid TemplateSyntaxError.)
        if 'role_name_en' in self.fields:
            self.fields['role_name_en'].widget.attrs.update(
                {'class': 'field-input'}
            )
        if 'role_name_ar' in self.fields:
            self.fields['role_name_ar'].widget.attrs.update(
                {'class': 'field-input', 'dir': 'rtl'}
            )
        if 'description' in self.fields:
            # Keep it simple: style as a regular input unless widget is textarea.
            desc_widget = self.fields['description'].widget
            extra_class = 'field-textarea' if desc_widget.__class__.__name__ == 'Textarea' else ''
            desc_widget.attrs.update(
                {'class': ('field-input ' + extra_class).strip()}
            )


class AdminUserForm(forms.ModelForm):
    class Meta:
        model = AdminUser
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'role', 'status']
        widgets = {
            'status': forms.Select(),
            'role': forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        # Only Active roles in dropdown (creation + edit).
        active_roles = Role.objects.filter(status='Active').order_by('role_name_en')
        current_role = getattr(self.instance, 'role', None)
        if current_role and current_role.pk and current_role not in active_roles:
            active_roles = active_roles | Role.objects.filter(pk=current_role.pk)
        self.fields['role'].queryset = active_roles
        self.fields['role'].required = True

    def clean_email(self):
        value = self.cleaned_data.get('email', '').strip().lower()
        qs = AdminUser.objects.filter(email=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Email must be unique.')
        return value


class MyAccountForm(forms.ModelForm):
    new_password = forms.CharField(
        required=False,
        label='New Password',
        widget=forms.PasswordInput(
            attrs={'placeholder': 'Leave blank to keep current', 'class': 'field-input'}
        ),
    )
    confirm_password = forms.CharField(
        required=False,
        label='Confirm Password',
        widget=forms.PasswordInput(
            attrs={'placeholder': 'Re-type new password', 'class': 'field-input'}
        ),
    )

    class Meta:
        model = AdminUser
        fields = ['first_name', 'last_name', 'email', 'phone_number']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['email'].disabled = not bool(getattr(self.instance, 'is_root', False))

    def clean_email(self):
        if not bool(getattr(self.instance, 'is_root', False)):
            return getattr(self.instance, 'email', '')

        value = (self.cleaned_data.get('email') or '').strip().lower()
        qs = AdminUser.objects.filter(email=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Email must be unique.')
        return value

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password or confirm_password:
            if new_password != confirm_password:
                raise ValidationError('Passwords do not match.')
            if len(new_password) < 8:
                raise ValidationError('Password must be at least 8 characters.')
            if not re.search(r'[a-z]', new_password):
                raise ValidationError('Password must include a lowercase letter.')
            if not re.search(r'[A-Z]', new_password):
                raise ValidationError('Password must include an uppercase letter.')
            if not re.search(r'\d', new_password):
                raise ValidationError('Password must include a number.')
            if not re.search(r'[^A-Za-z0-9]', new_password):
                raise ValidationError('Password must include a special character.')
        return cleaned_data


class CountryForm(forms.ModelForm):
    class Meta:
        model = Country
        fields = ['country_code', 'name_en', 'name_ar', 'is_active']

    def __init__(self, *args, **kwargs):
        is_edit = kwargs.pop('is_edit', False)
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)

        if 'name_ar' in self.fields:
            self.fields['name_ar'].widget.attrs.setdefault('dir', 'rtl')
            self.fields['name_ar'].widget.attrs.setdefault(
                'placeholder', 'الاسم بالعربية'
            )

        if is_edit and 'country_code' in self.fields:
            self.fields['country_code'].disabled = True
            self.fields['country_code'].help_text = (
                'Country code cannot be changed once saved.'
            )

        if 'is_active' in self.fields:
            self.fields['is_active'].widget.attrs.update({
                'class': 'form-check-input',
                'role': 'switch',
                'id': 'id_country_is_active'
            })

    def clean_country_code(self):
        # Disabled fields are not included in `cleaned_data`, so fallback to
        # the instance value when editing.
        value = self.cleaned_data.get('country_code')
        if value is None:
            value = getattr(self.instance, 'country_code', '') if self.instance else ''

        if value:
            value = value.upper().strip()
            if not re.fullmatch(r'[A-Z]+', value):
                raise forms.ValidationError(
                    'Country code must contain letters only.'
                )
        return value


class CurrencyForm(forms.ModelForm):
    class Meta:
        model = Currency
        fields = [
            'currency_code',
            'name_en',
            'name_ar',
            'currency_symbol',
            'decimal_places',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        is_edit = kwargs.pop('is_edit', False)
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)

        # Ensure dropdowns / templates show a default if user doesn't supply it.
        if 'decimal_places' in self.fields:
            self.fields['decimal_places'].required = False

        if is_edit and 'currency_code' in self.fields:
            self.fields['currency_code'].disabled = True
            self.fields['currency_code'].help_text = (
                'Currency code cannot be changed once saved.'
            )

        if 'is_active' in self.fields:
            self.fields['is_active'].widget.attrs.update({
                'class': 'form-check-input',
                'role': 'switch',
                'id': 'id_currency_is_active'
            })

    def clean_currency_code(self):
        value = self.cleaned_data.get('currency_code')
        if value is None:
            value = getattr(self.instance, 'currency_code', '') if self.instance else ''

        if value:
            value = value.upper().strip()
            if not re.fullmatch(r'[A-Z]+', value):
                raise forms.ValidationError(
                    'Currency code must contain letters only.'
                )
        return value

    def clean_decimal_places(self):
        value = self.cleaned_data.get('decimal_places', None)
        if value is None:
            if getattr(self.instance, 'pk', None):
                return self.instance.decimal_places
            return 2

        if value not in [0, 1, 2, 3]:
            raise forms.ValidationError(
                'Decimal places must be 0, 1, 2, or 3.'
            )
        return value


class TaxCodeForm(forms.ModelForm):
    DEFAULT_CHOICES = [
        ('country', 'Set as Country Default'),
        ('international', 'Set as International Default'),
    ]

    default_type = forms.ChoiceField(
        choices=DEFAULT_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        required=False,
        label='Default Type'
    )

    class Meta:
        model = TaxCode
        fields = [
            'tax_code',
            'name_en',
            'name_ar',
            'rate_percent',
            'applicable_country_code',
            'is_default_for_country',
            'is_international_default',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        is_edit = kwargs.pop('is_edit', False)
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        if is_edit:
            self.fields['tax_code'].disabled = True
            
            if self.instance.is_default_for_country:
                self.initial['default_type'] = 'country'
            elif self.instance.is_international_default:
                self.initial['default_type'] = 'international'
            else:
                self.initial['default_type'] = 'none'

        self.fields['applicable_country_code'].queryset = (
            Country.objects.filter(is_active=True).order_by('name_en')
        )

        if 'is_active' in self.fields:
            self.fields['is_active'].widget.attrs.update({
                'class': 'form-check-input',
                'role': 'switch',
                'id': 'id_taxcode_is_active'
            })

    def clean(self):
        cleaned = super().clean()
        applicable_country = cleaned.get('applicable_country_code')
        default_type = cleaned.get('default_type')
        
        # Set individual boolean fields based on radio selection
        is_default_for_country = (default_type == 'country')
        is_international_default = (default_type == 'international')

        cleaned['is_default_for_country'] = is_default_for_country
        cleaned['is_international_default'] = is_international_default
        self.instance.is_default_for_country = is_default_for_country
        self.instance.is_international_default = is_international_default

        if is_default_for_country and is_international_default:
            raise forms.ValidationError(
                'A tax code cannot be both country default and '
                'international default at the same time.'
            )

        if is_default_for_country and applicable_country is None:
            raise forms.ValidationError(
                'Country must be selected when setting as '
                'country default.'
            )

        if is_default_for_country and applicable_country is not None:
            qs = TaxCode.objects.filter(
                applicable_country_code=applicable_country,
                is_default_for_country=True,
                is_active=True,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    'A default tax code already exists for this country. '
                    'Deactivate it first.'
                )

        if is_international_default:
            qs = TaxCode.objects.filter(
                is_international_default=True,
                is_active=True,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    'An international default tax code already exists. '
                    'Deactivate it first.'
                )

        return cleaned


class GeneralTaxSettingsForm(forms.ModelForm):
    class Meta:
        model = GeneralTaxSettings
        fields = ['prices_include_tax', 'location_verification']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)


class LegalIdentityForm(forms.ModelForm):
    class Meta:
        model = LegalIdentity
        fields = [
            'company_logo',
            'company_name_en',
            'company_name_ar',
            'company_country_code',
            'commercial_register',
            'tax_number',
            'registered_address',
            'support_email',
            'support_phone',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['company_country_code'].queryset = (
            Country.objects.filter(is_active=True).order_by('name_en')
        )
        # Required identity fields for legal profile completeness.
        required_fields = {
            'company_logo',
            'company_name_en',
            'company_name_ar',
            'company_country_code',
        }
        for field_name, field in self.fields.items():
            field.required = field_name in required_fields


class GlobalSystemRulesForm(forms.ModelForm):
    class Meta:
        model = GlobalSystemRules
        fields = [
            'system_timezone',
            'default_date_format',
            'grace_period_days',
            'standard_billing_cycle',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)

    def clean_system_timezone(self):
        value = self.cleaned_data.get('system_timezone')
        if value not in pytz.all_timezones:
            raise forms.ValidationError(
                "Invalid timezone. Use format like "
                "'Asia/Riyadh' or 'UTC'."
            )
        return value

    def clean_standard_billing_cycle(self):
        value = self.cleaned_data.get('standard_billing_cycle')
        if value is not None and value < 1:
            raise forms.ValidationError(
                'Billing cycle must be at least 1 day.'
            )
        return value

    def clean_grace_period_days(self):
        value = self.cleaned_data.get('grace_period_days')
        if value is not None and value < 0:
            raise forms.ValidationError(
                'Grace period cannot be negative.'
            )
        return value


class BaseCurrencyForm(forms.ModelForm):
    class Meta:
        model = BaseCurrencyConfig
        fields = ['base_currency']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['base_currency'].queryset = (
            Currency.objects.filter(is_active=True).order_by('name_en')
        )


class ExchangeRateForm(forms.ModelForm):
    class Meta:
        model = ExchangeRate
        fields = ['currency', 'exchange_rate', 'is_active']

    def __init__(self, *args, **kwargs):
        base_currency_code = kwargs.pop('base_currency_code', None)
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        qs = Currency.objects.filter(is_active=True)
        if base_currency_code:
            qs = qs.exclude(currency_code=base_currency_code)
        self.fields['currency'].queryset = qs.order_by('name_en')

    def clean_exchange_rate(self):
        value = self.cleaned_data.get('exchange_rate')
        if value is not None and value <= 0:
            raise forms.ValidationError(
                'Exchange rate must be greater than 0.'
            )
        return value


class SubscriptionPlanForm(forms.ModelForm):
    MAX_FIELDS = [
        'max_internal_users',
        'max_internal_trucks',
        'max_external_trucks',
        'max_active_drivers',
        'max_monthly_shipments',
        'max_storage_gb',
    ]

    class Meta:
        model = SubscriptionPlan
        fields = [
            'plan_name_en',
            'plan_name_ar',
            'base_cycle_days',
            'is_active',
            'max_internal_users',
            'max_internal_trucks',
            'max_external_trucks',
            'max_active_drivers',
            'max_monthly_shipments',
            'max_storage_gb',
            'has_driver_app',
            'backup_restore_level',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)

        switch = lambda el_id: forms.CheckboxInput(
            attrs={
                'class': 'form-check-input',
                'role': 'switch',
                'id': el_id,
            }
        )
        if 'is_active' in self.fields:
            self.fields['is_active'].widget = switch('id_plan_is_active')
        if 'has_driver_app' in self.fields:
            self.fields['has_driver_app'].widget = switch('id_plan_has_driver_app')

        for field_name in self.MAX_FIELDS:
            if field_name in self.fields:
                self.fields[field_name].help_text = 'Enter -1 for Unlimited'

    def clean(self):
        cleaned = super().clean()

        for field_name in self.MAX_FIELDS:
            value = cleaned.get(field_name)
            if value is not None and value < -1:
                raise forms.ValidationError(
                    'Enter -1 for unlimited or a positive number.'
                )

        base_cycle_days = cleaned.get('base_cycle_days')
        if base_cycle_days is not None and base_cycle_days < 1:
            raise forms.ValidationError(
                'Base cycle days must be at least 1.'
            )

        return cleaned


class PlanPricingCycleForm(forms.ModelForm):
    class Meta:
        model = PlanPricingCycle
        fields = ['number_of_cycles', 'currency', 'price', 'is_admin_only_cycle']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['currency'].queryset = (
            Currency.objects.filter(is_active=True).order_by('name_en')
        )

    def clean_number_of_cycles(self):
        value = self.cleaned_data.get('number_of_cycles')
        if value is not None and value < 1:
            raise forms.ValidationError(
                'Number of cycles must be at least 1.'
            )
        return value

    def clean_price(self):
        value = self.cleaned_data.get('price')
        if value is not None and value < 0:
            raise forms.ValidationError(
                'Price cannot be negative.'
            )
        return value


class AddOnsPricingPolicyForm(forms.ModelForm):
    PRICE_FIELDS = [
        'extra_internal_user_price',
        'extra_internal_truck_price',
        'extra_external_truck_price',
        'extra_driver_price',
        'extra_shipment_price',
        'extra_storage_gb_price',
    ]

    class Meta:
        model = AddOnsPricingPolicy
        fields = [
            'policy_name',
            'is_active',
            'extra_internal_user_price',
            'extra_internal_truck_price',
            'extra_external_truck_price',
            'extra_driver_price',
            'extra_shipment_price',
            'extra_storage_gb_price',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        if 'is_active' in self.fields:
            self.fields['is_active'].widget = forms.CheckboxInput(
                attrs={
                    'class': 'form-check-input',
                    'role': 'switch',
                    'id': 'id_addons_policy_is_active',
                }
            )

    def clean(self):
        cleaned = super().clean()
        for field_name in self.PRICE_FIELDS:
            value = cleaned.get(field_name)
            if value is not None and value < 0:
                raise forms.ValidationError(
                    'Price cannot be negative.'
                )
        return cleaned


class PromoCodeForm(forms.ModelForm):
    class Meta:
        model = PromoCode
        fields = [
            'code',
            'discount_type',
            'discount_value',
            'discount_duration',
            'valid_from',
            'valid_until',
            'max_uses',
            'is_active',
            'applicable_plans',
        ]
        widgets = {
            'valid_from': forms.DateTimeInput(
                attrs={'type': 'datetime-local'}
            ),
            'valid_until': forms.DateTimeInput(
                attrs={'type': 'datetime-local'}
            ),
            'applicable_plans': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['applicable_plans'].queryset = (
            SubscriptionPlan.objects.filter(is_active=True).order_by('plan_name_en')
        )
        self.fields['code'].help_text = 'Code is auto-converted to uppercase.'

        switch = forms.CheckboxInput(
            attrs={
                'class': 'form-check-input',
                'role': 'switch',
                'id': 'id_promo_is_active',
            }
        )
        self.fields['is_active'].widget = switch

        dv = self.fields['discount_value']
        dv.widget.attrs.setdefault('step', '0.01')
        dv.widget.attrs.setdefault('min', '0')

    def clean_code(self):
        value = self.cleaned_data.get('code', '')
        value = value.upper().strip()
        if not value.isalnum():
            raise forms.ValidationError(
                'Code must be alphanumeric only '
                '(letters and numbers, no spaces or symbols).'
            )
        return value

    def clean_discount_value(self):
        value = self.cleaned_data.get('discount_value')
        discount_type = self.cleaned_data.get('discount_type') or (
            self.data.get('discount_type') or ''
        )
        if value is None:
            return value
        if value <= 0:
            raise forms.ValidationError(
                'Discount value must be greater than 0.'
            )
        if discount_type == 'Percentage' and value > 100:
            raise forms.ValidationError(
                'Percentage discount cannot exceed 100.'
            )
        return value

    def clean(self):
        cleaned = super().clean()
        valid_from = cleaned.get('valid_from')
        valid_until = cleaned.get('valid_until')
        max_uses = cleaned.get('max_uses')

        if valid_until and valid_from:
            if valid_until <= valid_from:
                raise forms.ValidationError(
                    'Valid Until must be after Valid From.'
                )

        if max_uses is not None and max_uses < 1:
            raise forms.ValidationError(
                'Max uses must be at least 1 if specified.'
            )

        return cleaned


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = [
            'bank_name',
            'account_holder_name',
            'iban_number',
            'account_number',
            'swift_code',
            'currency',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['currency'].queryset = (
            Currency.objects.filter(is_active=True).order_by('name_en')
        )

    def clean_iban_number(self):
        value = self.cleaned_data.get('iban_number', '')
        value = value.upper().replace(' ', '').strip()
        if len(value) < 15 or len(value) > 34:
            raise forms.ValidationError(
                'IBAN must be between 15 and 34 characters.'
            )
        if not value[:2].isalpha():
            raise forms.ValidationError(
                'IBAN must start with a 2-letter country code '
                '(e.g. SA, AE, GB).'
            )
        if not value[2:4].isdigit():
            raise forms.ValidationError(
                'IBAN characters 3-4 must be digits.'
            )
        if not value.isalnum():
            raise forms.ValidationError(
                'IBAN must contain only letters and numbers.'
            )
        return value

    def clean_account_number(self):
        value = self.cleaned_data.get('account_number', '')
        if not value.isdigit():
            raise forms.ValidationError(
                'Account number must contain digits only.'
            )
        return value

    def clean_swift_code(self):
        value = self.cleaned_data.get('swift_code', '')
        if value:
            value = value.upper().strip()
            if len(value) not in [8, 11]:
                raise forms.ValidationError(
                    'SWIFT code must be 8 or 11 characters.'
                )
            if not value.isalnum():
                raise forms.ValidationError(
                    'SWIFT code must be alphanumeric only.'
                )
        return value


class PaymentGatewayForm(forms.ModelForm):
    class Meta:
        model = PaymentGateway
        fields = [
            'gateway_name',
            'environment',
            'credentials_payload',
            'is_active',
        ]
        widgets = {
            'credentials_payload': forms.Textarea(attrs={'rows': 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['credentials_payload'].help_text = (
            'Enter JSON object e.g. '
            '{"public_key": "pk_test_...", "secret_key": "sk_..."}'
        )

    def clean_credentials_payload(self):
        value = self.cleaned_data.get('credentials_payload')
        if value is None:
            raise forms.ValidationError(
                'Credentials payload is required.'
            )
        if not isinstance(value, dict):
            raise forms.ValidationError(
                'Credentials must be a JSON object '
                '(e.g. {"key": "value"}), not an array.'
            )
        if len(value) == 0:
            raise forms.ValidationError(
                'Credentials object cannot be empty.'
            )
        return value


class PaymentMethodForm(forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = [
            'method_name_en',
            'method_name_ar',
            'method_type',
            'supported_currencies',
            'gateway',
            'dedicated_bank_account',
            'logo',
            'display_order',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['gateway'].queryset = (
            PaymentGateway.objects.filter(is_active=True).order_by('gateway_name')
        )
        self.fields['dedicated_bank_account'].queryset = (
            BankAccount.objects.filter(is_active=True).order_by('bank_name')
        )

    def clean(self):
        cleaned = super().clean()
        method_type = cleaned.get('method_type')
        gateway = cleaned.get('gateway')
        bank_account = cleaned.get('dedicated_bank_account')
        supported_currencies = cleaned.get('supported_currencies')

        if method_type == 'Online_Gateway' and not gateway:
            raise forms.ValidationError(
                'A payment gateway must be selected for '
                'Online Gateway methods.'
            )

        if method_type == 'Online_Gateway' and bank_account:
            raise forms.ValidationError(
                'Dedicated bank account must be empty for '
                'Online Gateway methods.'
            )

        if method_type == 'Offline_Bank' and gateway:
            raise forms.ValidationError(
                'Payment gateway must be empty for '
                'Offline Bank methods.'
            )

        if not supported_currencies:
            raise forms.ValidationError(
                'At least one supported currency is required.'
            )

        if not isinstance(supported_currencies, list):
            raise forms.ValidationError(
                'Supported currencies must be a JSON array '
                'e.g. ["SAR", "USD"]'
            )

        if len(supported_currencies) == 0:
            raise forms.ValidationError(
                'At least one currency must be in the list.'
            )

        from .models import Currency
        for code in supported_currencies:
            if not Currency.objects.filter(
                    currency_code=code,
                    is_active=True).exists():
                raise forms.ValidationError(
                    f"Currency '{code}' is not active "
                    f"or does not exist."
                )

        return cleaned


class CommGatewayForm(forms.ModelForm):
    class Meta:
        model = CommGateway
        fields = [
            'gateway_type',
            'provider_name',
            'host_url',
            'port',
            'username_key',
            'password_secret',
            'sender_id',
            'encryption_type',
            'is_active',
        ]
        widgets = {
            'password_secret': forms.PasswordInput(render_value=False),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)

    def clean(self):
        cleaned = super().clean()
        gateway_type = (cleaned.get('gateway_type') or '').strip()
        port = cleaned.get('port')
        host_url = (cleaned.get('host_url') or '').strip()
        encryption_type = cleaned.get('encryption_type')

        if gateway_type == 'Email':
            if not port:
                raise forms.ValidationError(
                    'Port is required for Email (SMTP) gateways.'
                )
            if port not in [25, 465, 587, 2525]:
                raise forms.ValidationError(
                    'Common SMTP ports: 25, 465, 587, 2525.'
                )
        elif gateway_type == 'SMS':
            # SMS APIs do not use SMTP fields.
            cleaned['port'] = None
            cleaned['encryption_type'] = None
            if not host_url.lower().startswith(('http://', 'https://')):
                raise forms.ValidationError(
                    'SMS Host / API URL must start with http:// or https://'
                )

        return cleaned


class NotificationTemplateForm(forms.ModelForm):
    class Meta:
        model = NotificationTemplate
        fields = [
            'template_name',
            'channel_type',
            'category',
            'subject_en',
            'subject_ar',
            'body_en',
            'body_ar',
            'is_active',
        ]
        widgets = {
            'body_en': forms.Textarea(attrs={'rows': 8}),
            'body_ar': forms.Textarea(attrs={'rows': 8, 'dir': 'rtl'}),
            'subject_ar': forms.TextInput(attrs={'dir': 'rtl'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        if 'is_active' in self.fields:
            self.fields['is_active'].widget.attrs.update({
                'class': 'form-check-input',
                'role': 'switch',
                'id': 'id_template_is_active'
            })

    def clean(self):
        cleaned = super().clean()
        channel_type = cleaned.get('channel_type')
        subject_en = cleaned.get('subject_en')
        subject_ar = cleaned.get('subject_ar')

        if channel_type == 'Email':
            if not subject_en:
                raise forms.ValidationError(
                    'Subject (English) is required for '
                    'Email templates.'
                )
            if not subject_ar:
                raise forms.ValidationError(
                    'Subject (Arabic) is required for '
                    'Email templates.'
                )
        elif channel_type == 'SMS':
            # Keep subject fields empty for SMS templates.
            cleaned['subject_en'] = ''
            cleaned['subject_ar'] = ''

        return cleaned


class EventMappingForm(forms.ModelForm):
    class Meta:
        model = EventMapping
        fields = [
            'system_event',
            'primary_channel',
            'primary_template',
            'fallback_channel',
            'fallback_template',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['primary_template'].queryset = (
            NotificationTemplate.objects.filter(is_active=True)
        )
        self.fields['fallback_template'].queryset = (
            NotificationTemplate.objects.filter(is_active=True)
        )

        if self.instance and self.instance.pk:
            if self.instance.primary_channel:
                self.fields['primary_template'].queryset = (
                    NotificationTemplate.objects.filter(
                        is_active=True,
                        channel_type=self.instance.primary_channel,
                    )
                )
            if self.instance.fallback_channel:
                self.fields['fallback_template'].queryset = (
                    NotificationTemplate.objects.filter(
                        is_active=True,
                        channel_type=self.instance.fallback_channel,
                    )
                )

        # Also filter while creating/updating from posted form data.
        posted_primary_channel = (self.data.get('primary_channel') or '').strip()
        if posted_primary_channel in ['Email', 'SMS']:
            self.fields['primary_template'].queryset = (
                NotificationTemplate.objects.filter(
                    is_active=True,
                    channel_type=posted_primary_channel,
                )
            )

        posted_fallback_channel = (self.data.get('fallback_channel') or '').strip()
        if posted_fallback_channel in ['Email', 'SMS']:
            self.fields['fallback_template'].queryset = (
                NotificationTemplate.objects.filter(
                    is_active=True,
                    channel_type=posted_fallback_channel,
                )
            )

    def clean(self):
        cleaned = super().clean()
        primary_channel = cleaned.get('primary_channel')
        fallback_channel = cleaned.get('fallback_channel')
        primary_template = cleaned.get('primary_template')
        fallback_template = cleaned.get('fallback_template')
        system_event = cleaned.get('system_event')

        if primary_template and primary_template.channel_type != primary_channel:
            raise forms.ValidationError(
                'Primary template channel type must match '
                'primary channel.'
            )

        if fallback_channel:
            if fallback_channel == primary_channel:
                raise forms.ValidationError(
                    'Fallback channel cannot be same as '
                    'primary channel.'
                )
            if not fallback_template:
                raise forms.ValidationError(
                    'Fallback template is required when '
                    'fallback channel is selected.'
                )
            if fallback_template and fallback_template.channel_type != fallback_channel:
                raise forms.ValidationError(
                    'Fallback template channel type must '
                    'match fallback channel.'
                )

        return cleaned


class PushNotificationForm(forms.ModelForm):
    class Meta:
        model = PushNotification
        fields = [
            'internal_name',
            'title_en',
            'title_ar',
            'message_en',
            'message_ar',
            'action_link',
            'trigger_mode',
            'linked_event',
            'target_audience',
            'specific_target_id',
            'scheduled_at',
            'is_active',
            'dispatch_status',
        ]
        widgets = {
            'message_en': forms.Textarea(attrs={'rows': 4}),
            'message_ar': forms.Textarea(attrs={'rows': 4, 'dir': 'rtl'}),
            'title_ar': forms.TextInput(attrs={'dir': 'rtl'}),
            'scheduled_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)

    def clean(self):
        cleaned = super().clean()
        trigger_mode = cleaned.get('trigger_mode')
        linked_event = cleaned.get('linked_event')
        target_audience = cleaned.get('target_audience')
        specific_target_id = cleaned.get('specific_target_id')
        scheduled_at = cleaned.get('scheduled_at')

        if trigger_mode == 'System_Event':
            if not linked_event:
                raise forms.ValidationError(
                    'Linked event is required for '
                    'System Event mode.'
                )
            # System-event rules act like active routing definitions, not campaigns.
            cleaned['target_audience'] = None
            cleaned['specific_target_id'] = ''
            cleaned['scheduled_at'] = None
            cleaned['dispatch_status'] = 'Draft'

        if trigger_mode == 'Manual_Broadcast':
            if not target_audience:
                raise forms.ValidationError(
                    'Target audience is required for '
                    'Manual Broadcast mode.'
                )
            if target_audience == 'Specific' and not specific_target_id:
                raise forms.ValidationError(
                    'Specific target ID is required when '
                    'audience is Specific.'
                )
            if target_audience != 'Specific':
                cleaned['specific_target_id'] = ''
            # Manual broadcast does not use linked_event/is_active rule flags.
            cleaned['linked_event'] = None
            cleaned['is_active'] = True
            # Scheduled campaigns are marked Scheduled; otherwise Draft until queued.
            if scheduled_at:
                cleaned['dispatch_status'] = 'Scheduled'
            elif not cleaned.get('dispatch_status'):
                cleaned['dispatch_status'] = 'Draft'

        return cleaned


class SystemBannerForm(forms.ModelForm):
    class Meta:
        model = SystemBanner
        fields = [
            'title_en',
            'title_ar',
            'message_en',
            'message_ar',
            'severity',
            'is_dismissible',
            'valid_from',
            'valid_until',
            'is_active',
        ]
        widgets = {
            'message_en': forms.Textarea(attrs={'rows': 3}),
            'message_ar': forms.Textarea(attrs={'rows': 3, 'dir': 'rtl'}),
            'title_ar': forms.TextInput(attrs={'dir': 'rtl'}),
            'valid_from': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'valid_until': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)

    def clean(self):
        cleaned = super().clean()
        valid_from = cleaned.get('valid_from')
        valid_until = cleaned.get('valid_until')

        if valid_until and valid_from:
            if valid_until <= valid_from:
                raise forms.ValidationError(
                    'Valid Until must be after Valid From.'
                )

        return cleaned


class InternalAlertRouteForm(forms.ModelForm):
    class Meta:
        model = InternalAlertRoute
        fields = [
            'trigger_event',
            'notify_role',
            'notify_custom_email',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['notify_role'].queryset = (
            Role.objects.filter(status='Active').order_by('role_name_en')
        )

    def clean(self):
        cleaned = super().clean()
        notify_role = cleaned.get('notify_role')
        notify_custom_email = cleaned.get('notify_custom_email')

        if not notify_role and not notify_custom_email:
            raise forms.ValidationError(
                'At least one of Role or Custom Email '
                'must be provided.'
            )

        return cleaned


class TenantProfileCreateForm(forms.ModelForm):
    class Meta:
        model = TenantProfile
        fields = [
            'company_name',
            'registration_number',
            'tax_number',
            'primary_email',
            'primary_phone',
            'country',
            'account_status',
            'assigned_sales_rep',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['country'].queryset = (
            Country.objects.filter(is_active=True).order_by('name_en')
        )
        self.fields['country'].required = False
        self.fields['tax_number'].required = False
        self.fields['assigned_sales_rep'].queryset = (
            AdminUser.objects.filter(status='Active').order_by(
                'first_name', 'last_name'
            )
        )
        self.fields['assigned_sales_rep'].required = False

    def clean_primary_email(self):
        value = (self.cleaned_data.get('primary_email') or '').strip().lower()
        if not value:
            raise ValidationError('Primary email is required.')
        if TenantProfile.objects.filter(primary_email__iexact=value).exists():
            raise ValidationError('Primary email must be unique across tenants.')
        return value


class TenantProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = TenantProfile
        fields = [
            'company_name',
            'registration_number',
            'tax_number',
            'primary_email',
            'primary_phone',
            'country',
            'account_status',
            'assigned_sales_rep',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['country'].queryset = (
            Country.objects.filter(is_active=True).order_by('name_en')
        )
        self.fields['country'].required = False
        self.fields['tax_number'].required = False
        active_reps = AdminUser.objects.filter(status='Active').order_by(
            'first_name', 'last_name'
        )
        current = getattr(self.instance, 'assigned_sales_rep', None)
        if current and current.pk and current not in active_reps:
            active_reps = active_reps | AdminUser.objects.filter(pk=current.pk)
        self.fields['assigned_sales_rep'].queryset = active_reps
        self.fields['assigned_sales_rep'].required = False
        if self.instance.pk:
            pass

    def clean_primary_email(self):
        value = (self.cleaned_data.get('primary_email') or '').strip().lower()
        if not value:
            raise ValidationError('Primary email is required.')
        qs = TenantProfile.objects.filter(primary_email__iexact=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Primary email must be unique across tenants.')
        return value


class SupportCategoryForm(forms.ModelForm):
    class Meta:
        model = SupportCategory
        fields = ['name_en', 'name_ar', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['name_en'].widget.attrs.update({
            'maxlength': '100',
        })
        self.fields['name_ar'].widget.attrs.update({
            'dir': 'rtl',
            'maxlength': '100',
        })
        if 'is_active' in self.fields:
            self.fields['is_active'].widget = forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'role': 'switch',
            })

    def clean_name_en(self):
        value = self.cleaned_data.get('name_en', '').strip()
        if not value:
            raise forms.ValidationError(
                'English name is required.'
            )
        qs = SupportCategory.objects.filter(name_en__iexact=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                'A support category with this English name already exists.'
            )
        return value

    def clean_name_ar(self):
        value = self.cleaned_data.get('name_ar', '').strip()
        if not value:
            raise forms.ValidationError(
                'Arabic name is required.'
            )
        qs = SupportCategory.objects.filter(name_ar__iexact=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                'A support category with this Arabic name already exists.'
            )
        return value


class CannedResponseForm(forms.ModelForm):
    class Meta:
        model = CannedResponse
        fields = ['title', 'message_body', 'is_active']
        widgets = {
            'message_body': forms.Textarea(attrs={'rows': 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['title'].widget.attrs.update({
            'maxlength': '100',
        })
        self.fields['message_body'].widget.attrs.update({
            'rows': 8,
        })
        if 'is_active' in self.fields:
            self.fields['is_active'].widget = forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'role': 'switch',
            })

    def clean_title(self):
        value = self.cleaned_data.get('title', '').strip()
        if not value:
            raise forms.ValidationError('Template title is required.')
        qs = CannedResponse.objects.filter(title__iexact=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                'A canned response with this title already exists.'
            )
        return value

    def clean_message_body(self):
        value = self.cleaned_data.get('message_body', '').strip()
        if not value:
            raise forms.ValidationError('Message content is required.')
        return value


class SubscriptionFAQForm(forms.ModelForm):
    class Meta:
        model = SubscriptionFAQ
        fields = ['question', 'answer', 'display_order', 'is_active']
        widgets = {
            'answer': forms.Textarea(attrs={'rows': 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['question'].widget.attrs.update({'maxlength': '255'})
        self.fields['display_order'].widget.attrs.update({'min': 1})
        self.fields['answer'].widget.attrs.update({'rows': 6})
        if 'is_active' in self.fields:
            self.fields['is_active'].widget = forms.CheckboxInput(
                attrs={'class': 'form-check-input', 'role': 'switch'}
            )

    def clean_question(self):
        value = (self.cleaned_data.get('question') or '').strip()
        if not value:
            raise forms.ValidationError('Question is required.')
        qs = SubscriptionFAQ.objects.filter(question__iexact=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('This FAQ question already exists.')
        return value

    def clean_answer(self):
        value = (self.cleaned_data.get('answer') or '').strip()
        if not value:
            raise forms.ValidationError('Answer is required.')
        return value


class SupportTicketForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = [
            'tenant',
            'subject',
            'category',
            'description',
            'priority',
            'status',
            'assigned_to',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['tenant'].queryset = TenantProfile.objects.filter(
            account_status='Active'
        ).order_by('company_name')
        self.fields['category'].queryset = SupportCategory.objects.filter(
            is_active=True
        ).order_by('name_en')
        self.fields['assigned_to'].queryset = AdminUser.objects.filter(
            status='Active'
        ).order_by('first_name')


class TicketAssignForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ['assigned_to']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['assigned_to'].queryset = AdminUser.objects.filter(
            status='Active'
        ).order_by('first_name')
        self.fields['assigned_to'].required = False


class TicketPriorityForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ['priority']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)


class AdminReplyForm(forms.ModelForm):
    class Meta:
        model = TicketReply
        fields = ['message_body', 'attachment', 'is_internal']
        widgets = {
            'message_body': forms.Textarea(attrs={'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)


class TenantReplyForm(forms.ModelForm):
    class Meta:
        model = TicketReply
        fields = ['message_body', 'attachment']
        widgets = {
            'message_body': forms.Textarea(attrs={'rows': 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)


class TenantTicketCreateForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ['subject', 'category', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        self.fields['category'].queryset = SupportCategory.objects.filter(
            is_active=True
        ).order_by('name_en')


class TenantSecuritySettingsForm(forms.ModelForm):
    class Meta:
        model = TenantSecuritySettings
        fields = [
            'tenant_web_timeout_hours',
            'driver_app_timeout_days',
            'max_failed_logins',
            'lockout_duration_minutes',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)

    def clean_tenant_web_timeout_hours(self):
        value = self.cleaned_data.get('tenant_web_timeout_hours')
        if value and value < 1:
            raise forms.ValidationError(
                'Timeout must be at least 1 hour.'
            )
        return value

    def clean_driver_app_timeout_days(self):
        value = self.cleaned_data.get('driver_app_timeout_days')
        if value and value < 1:
            raise forms.ValidationError(
                'Timeout must be at least 1 day.'
            )
        return value

    def clean_max_failed_logins(self):
        value = self.cleaned_data.get('max_failed_logins')
        if value and value < 1:
            raise forms.ValidationError(
                'Must allow at least 1 attempt.'
            )
        return value


class AdminSecuritySettingsForm(forms.ModelForm):
    class Meta:
        model = AdminSecuritySettings
        fields = [
            'session_timeout_minutes',
            'max_failed_logins',
            'lockout_duration_minutes',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_premium_styling(self)
        if 'session_timeout_minutes' in self.fields:
            self.fields['session_timeout_minutes'].widget.attrs.update({
                'placeholder': 'e.g. 60 to 240',
                'min': 1,
            })
        if 'max_failed_logins' in self.fields:
            self.fields['max_failed_logins'].widget.attrs.update({
                'placeholder': 'e.g. 3',
                'min': 1,
            })
        if 'lockout_duration_minutes' in self.fields:
            self.fields['lockout_duration_minutes'].widget.attrs.update({
                'placeholder': 'e.g. 15 or 30',
                'min': 1,
            })

    def clean_session_timeout_minutes(self):
        value = self.cleaned_data.get('session_timeout_minutes')
        if value and value < 1:
            raise forms.ValidationError(
                'Session timeout must be at least 1 minute.'
            )
        return value

    def clean_max_failed_logins(self):
        value = self.cleaned_data.get('max_failed_logins')
        if value and value < 1:
            raise forms.ValidationError(
                'Must allow at least 1 attempt.'
            )
        return value

    def clean_lockout_duration_minutes(self):
        value = self.cleaned_data.get('lockout_duration_minutes')
        if value and value < 1:
            raise forms.ValidationError(
                'Lockout duration must be at least 1 minute.'
            )
        return value
