from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from superadmin.models import Country
from tenant_workspace.models import (
    TenantAddressMaster,
    TenantClientAccount,
    TenantLocationMaster,
)


class PublicCountryChoiceField(forms.ChoiceField):
    """
    Countries are loaded from the shared (public) schema. ModelChoice/queryset
    iteration on tenant connections produces empty choices or failing lookups,
    so we materialize labels in ``schema_context('public')`` and return a live
    ``Country`` instance from ``clean()``.
    """

    def __init__(self, *, address_instance, **kwargs):
        self._address_instance = address_instance
        kwargs.setdefault('label', _('Country'))
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        if value in self.empty_values:
            return None
        with schema_context('public'):
            row = Country.objects.filter(pk=value).first()
        if row is None:
            raise ValidationError(_('Select a country from the master list.'))
        if not row.is_active:
            prior = getattr(self._address_instance, 'country_id', None)
            if (
                self._address_instance
                and self._address_instance.pk
                and prior
                and str(prior).strip().upper() == str(row.pk).strip().upper()
            ):
                return row
            raise ValidationError(_('Select a country from the master list.'))
        return row


def _digits_only(value: str, required: bool) -> str:
    s = ''.join(ch for ch in (value or '') if ch.isdigit())
    if required and not s:
        raise ValidationError('Digits only.')
    if value and ''.join(ch for ch in value if not ch.isspace()) and not s:
        raise ValidationError('Digits only.')
    return s


class TenantAddressMasterForm(forms.ModelForm):
    address_code_preview = forms.CharField(
        label=_('Address Code'),
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'readonly': True,
                'placeholder': _('Auto generated'),
            }
        ),
    )

    class Meta:
        model = TenantAddressMaster
        fields = (
            'client_account',
            'display_name',
            'arabic_label',
            'english_label',
            'address_category',
            'default_pickup_address',
            'default_delivery_address',
            'status',
            'country',
            'province',
            'city',
            'district',
            'street',
            'building_no',
            'postal_code',
            'address_line_1',
            'address_line_2',
            'map_link',
            'site_instructions',
            'contact_name',
            'position',
            'mobile_no_1',
            'mobile_no_2',
            'whatsapp_no',
            'phone_no',
            'email',
        )
        labels = {
            'address_category': _('Address Category'),
            'country': _('Country'),
        }
        widgets = {
            'client_account': forms.Select(attrs={'class': 'form-select'}),
            'display_name': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('e.g. Main Warehouse')}
            ),
            'arabic_label': forms.TextInput(
                attrs={'class': 'form-control', 'dir': 'rtl', 'placeholder': _('مثال: المستودع الرئيسي')}
            ),
            'english_label': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('e.g. Head Office')}
            ),
            'address_category': forms.Select(attrs={'class': 'form-select'}),
            'default_pickup_address': forms.CheckboxInput(
                attrs={'class': 'form-check-input', 'role': 'switch'}
            ),
            'default_delivery_address': forms.CheckboxInput(
                attrs={'class': 'form-check-input', 'role': 'switch'}
            ),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'country': forms.Select(attrs={'class': 'form-select'}),
            'province': forms.Select(attrs={'class': 'form-select'}),
            'city': forms.Select(attrs={'class': 'form-select'}),
            'district': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('District')}
            ),
            'street': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('Street name')}
            ),
            'building_no': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('e.g. 42')}
            ),
            'postal_code': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('Postal code')}
            ),
            'address_line_1': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('Full address line')}
            ),
            'address_line_2': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('Optional second line')}
            ),
            'map_link': forms.URLInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'https://maps.google.com/...',
                }
            ),
            'site_instructions': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': _('Delivery or pickup instructions.'),
                }
            ),
            'contact_name': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('Full name')}
            ),
            'position': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('Job title')}
            ),
            'mobile_no_1': forms.TextInput(
                attrs={'class': 'form-control phone-number', 'placeholder': _('Mobile number')}
            ),
            'mobile_no_2': forms.TextInput(
                attrs={'class': 'form-control phone-number', 'placeholder': _('Mobile number')}
            ),
            'whatsapp_no': forms.TextInput(
                attrs={'class': 'form-control phone-number', 'placeholder': _('WhatsApp number')}
            ),
            'phone_no': forms.TextInput(
                attrs={
                    'class': 'form-control phone-number',
                    'placeholder': _('Landline'),
                    'autocomplete': 'tel',
                    'inputmode': 'numeric',
                }
            ),
            'email': forms.EmailInput(
                attrs={'class': 'form-control', 'placeholder': 'email@example.com'}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['address_category'].choices = [
            (TenantAddressMaster.AddressCategory.PICKUP_ADDRESS, 'Pickup Address'),
            (TenantAddressMaster.AddressCategory.DELIVERY_ADDRESS, 'Delivery Address'),
            (TenantAddressMaster.AddressCategory.BOTH, 'Both'),
        ]

        if not self.instance.pk:
            self.fields.pop('address_code_preview', None)
            self.initial.setdefault('status', TenantAddressMaster.Status.ACTIVE)
            self.initial.setdefault('address_category', TenantAddressMaster.AddressCategory.PICKUP_ADDRESS)
            self.initial.setdefault('default_pickup_address', False)
            self.initial.setdefault('default_delivery_address', False)
        else:
            self.fields['address_code_preview'].initial = self.instance.address_code

        self.fields['status'].choices = [
            (TenantAddressMaster.Status.ACTIVE, TenantAddressMaster.Status.ACTIVE),
        ]

        self.fields['client_account'].empty_label = _('- Select client -')
        self.fields['client_account'].queryset = TenantClientAccount.objects.all().order_by(
            '-created_at'
        )
        self.fields.pop('country', None)
        country_pairs = self._build_country_choices()
        self.fields['country'] = PublicCountryChoiceField(
            address_instance=self.instance,
            choices=country_pairs,
            required=True,
            label=_('Country'),
            widget=forms.Select(attrs={'class': 'form-select'}),
        )
        cid_val = getattr(self.instance, 'country_id', None)
        if self.instance.pk and cid_val:
            self.fields['country'].initial = cid_val
        self.fields['province'] = forms.ChoiceField(
            required=True,
            label=_('Province'),
            choices=[('', _('Select province...'))],
            widget=forms.Select(attrs={'class': 'form-select'}),
        )
        self.fields['city'] = forms.ChoiceField(
            required=True,
            label=_('City'),
            choices=[('', _('Select city...'))],
            widget=forms.Select(attrs={'class': 'form-select'}),
        )
        self._populate_location_choices()

    def _build_country_choices(self):
        with schema_context('public'):
            cid = getattr(self.instance, 'country_id', None)
            if cid:
                qs = (
                    Country.objects.filter(Q(is_active=True) | Q(pk=cid))
                    .distinct()
                    .order_by('name_en')
                )
            else:
                qs = Country.objects.filter(is_active=True).order_by('name_en')
            rows = list(qs)
        return [('', _('Select country...'))] + [
            (c.country_code, f'{c.country_code} — {c.name_en}') for c in rows
        ]

    def _selected_country_code(self):
        if self.is_bound:
            return (self.data.get(self.add_prefix('country')) or '').strip()
        return str(getattr(self.instance, 'country_id', '') or self.initial.get('country') or '').strip()

    def _selected_province(self):
        if self.is_bound:
            return (self.data.get(self.add_prefix('province')) or '').strip()
        return str(
            getattr(self.instance, 'province', '') or self.initial.get('province') or ''
        ).strip()

    def _active_locations_for_country(self, country_code):
        qs = TenantLocationMaster.active_serviceable_objects.all()
        if country_code:
            qs = qs.filter(country_id=country_code)
        return qs

    def _populate_location_choices(self):
        country_code = self._selected_country_code()
        province_value = self._selected_province()
        location_qs = self._active_locations_for_country(country_code)
        province_rows = (
            location_qs.exclude(province='')
            .values_list('province', flat=True)
            .distinct()
            .order_by('province')
        )
        province_choices = [('', _('Select province...'))] + [(p, p) for p in province_rows]
        self.fields['province'].choices = province_choices
        valid_province_keys = {p for p, _ in province_choices[1:]}
        if province_value and province_value not in valid_province_keys:
            # Allow orphan values on initial GET (e.g. edit legacy row); never on POST — tampered
            # submissions must fail ChoiceField / clean() instead of being whitelisted.
            if not self.is_bound:
                self.fields['province'].choices.append((province_value, province_value))

        city_rows = (
            location_qs.filter(province=province_value)
            .values_list('display_label', flat=True)
            .distinct()
            .order_by('display_label')
        ) if province_value else []
        city_choices = [('', _('Select city...'))] + [(c, c) for c in city_rows]
        self.fields['city'].choices = city_choices
        city_value = (
            (self.data.get(self.add_prefix('city')) or '').strip()
            if self.is_bound
            else str(getattr(self.instance, 'city', '') or self.initial.get('city') or '').strip()
        )
        valid_city_keys = {c for c, _ in city_choices[1:]}
        if city_value and city_value not in valid_city_keys:
            if not self.is_bound:
                self.fields['city'].choices.append((city_value, city_value))

    def clean_map_link(self):
        v = (self.cleaned_data.get('map_link') or '').strip()
        if not v:
            return ''
        try:
            URLValidator()(v)
        except ValidationError:
            raise ValidationError(_('Enter a valid URL.'))
        return v

    def clean_building_no(self):
        raw = self.cleaned_data.get('building_no') or ''
        if not raw.strip():
            return ''
        if not raw.strip().isdigit():
            raise ValidationError(_('Numeric only.'))
        return raw.strip()

    def clean_mobile_no_1(self):
        return _digits_only(self.cleaned_data.get('mobile_no_1'), required=True)

    def clean_mobile_no_2(self):
        return _digits_only(self.cleaned_data.get('mobile_no_2'), required=False)

    def clean_whatsapp_no(self):
        return _digits_only(self.cleaned_data.get('whatsapp_no'), required=False)

    def clean_phone_no(self):
        return _digits_only(self.cleaned_data.get('phone_no'), required=False)

    def clean_email(self):
        return (self.cleaned_data.get('email') or '').strip()

    def clean_status(self):
        status = (self.cleaned_data.get('status') or '').strip()
        if status != TenantAddressMaster.Status.ACTIVE:
            raise ValidationError(_('Inactive status cannot be selected here.'))
        return TenantAddressMaster.Status.ACTIVE

    def clean(self):
        cleaned = super().clean()
        country = cleaned.get('country')
        province = (cleaned.get('province') or '').strip()
        city = (cleaned.get('city') or '').strip()

        province_ok = False
        if country and province:
            province_ok = TenantLocationMaster.active_serviceable_objects.filter(
                country_id=getattr(country, 'pk', country),
                province=province,
            ).exclude(province='').exists()
            if not province_ok:
                self.add_error(
                    'province',
                    _('Select a province from Location/Province master for the selected country.'),
                )

        if country and province and city and province_ok:
            exists = TenantLocationMaster.active_serviceable_objects.filter(
                country_id=getattr(country, 'pk', country),
                province=province,
                display_label=city,
            ).exists()
            if not exists:
                self.add_error(
                    'city',
                    _('Select a city from Location Master for the selected country and province.'),
                )
        return cleaned
