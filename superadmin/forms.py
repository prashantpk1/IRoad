import re

from django import forms
from django.core.exceptions import ValidationError

from .models import AdminUser, Country, Currency, Role


class LoginForm(forms.Form):
    email = forms.EmailField(max_length=100)
    password = forms.CharField(widget=forms.PasswordInput)


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
    class Meta:
        model = Role
        fields = ['role_name_en', 'role_name_ar', 'description', 'status']

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


class CountryForm(forms.ModelForm):
    class Meta:
        model = Country
        fields = ['country_code', 'name_en', 'name_ar', 'is_active']

    def __init__(self, *args, **kwargs):
        is_edit = kwargs.pop('is_edit', False)
        super().__init__(*args, **kwargs)

        if is_edit and 'country_code' in self.fields:
            self.fields['country_code'].disabled = True
            self.fields['country_code'].help_text = (
                'Country code cannot be changed once saved.'
            )

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

        # Ensure dropdowns / templates show a default if user doesn't supply it.
        if 'decimal_places' in self.fields:
            self.fields['decimal_places'].required = False

        if is_edit and 'currency_code' in self.fields:
            self.fields['currency_code'].disabled = True
            self.fields['currency_code'].help_text = (
                'Currency code cannot be changed once saved.'
            )

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

