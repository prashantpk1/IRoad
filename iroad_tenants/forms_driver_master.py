import re

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from config.text_validators import ArabicTextFormMixin
from superadmin.models import Country
from tenant_workspace.models import DriverMaster, TenantUser, TruckMaster

from iroad_tenants.forms_tenant_address import PublicCountryChoiceField

SAUDI_COUNTRY_CODE = 'SA'
SAUDI_DOCUMENT_NUMBER_MAX_LEN = 10
OTHER_PASSPORT_NUMBER_MAX_LEN = 15


def _nationality_country_code(country) -> str:
    if country is None:
        return ''
    return str(getattr(country, 'country_code', country) or '').strip().upper()


def passport_number_max_len(country_code: str) -> int:
    if country_code == SAUDI_COUNTRY_CODE:
        return SAUDI_DOCUMENT_NUMBER_MAX_LEN
    return OTHER_PASSPORT_NUMBER_MAX_LEN


def driver_current_assigned_truck(driver):
    if not driver or not getattr(driver, 'pk', None):
        return None
    return (
        TruckMaster.objects.filter(default_driver_id=driver)
        .order_by('-updated_at')
        .first()
    )


def driver_default_truck_queryset(*, driver=None, extra_truck_pks=None):
    """Active trucks plus any currently assigned or submitted truck choices."""
    qs = TruckMaster.active_objects.all()
    extra_pks = {str(pk).strip() for pk in (extra_truck_pks or []) if pk}
    if driver and driver.pk:
        extra_pks.update(
            str(pk)
            for pk in TruckMaster.objects.filter(default_driver_id=driver)
            .values_list('pk', flat=True)
        )
    if extra_pks:
        qs = (qs | TruckMaster.objects.filter(pk__in=extra_pks)).distinct()
    return qs.order_by('truck_code')


class DriverMasterForm(ArabicTextFormMixin, forms.ModelForm):
    """
    Driver master create/edit. ``driver_code`` is never collected here (auto /
    sequence elsewhere). ``nationality_country`` uses ``PublicCountryChoiceField``;
    it is attached in ``__init__`` because that field requires ``address_instance``.
    """

    class Meta:
        model = DriverMaster
        fields = [
            'user_account_id',
            'driver_source',
            'vendor_account_id',
            'driver_status',
            'driver_type',
            'arabic_name',
            'english_name',
            'nationality_country',
            'birth_date',
            'id_number',
            'id_expiry_date',
            'id_image',
            'passport_number',
            'passport_expiry_date',
            'passport_image',
            'dl_number',
            'dl_expiry_date',
            'dl_image',
            'card_number',
            'card_expiry_date',
            'card_image',
            'mobile_number',
            'whatsapp_number',
            'whatsapp_same_as_mobile',
        ]
        widgets = {
            'driver_source': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'vendor_account_id': forms.HiddenInput(),
            'driver_status': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'driver_type': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'arabic_name': forms.TextInput(
                attrs={
                    'class': 'form-control eal-arabic',
                    'dir': 'rtl',
                    'lang': 'ar',
                }
            ),
            'english_name': forms.TextInput(
                attrs={'class': 'form-control'}
            ),
            'birth_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                }
            ),
            'id_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'inputmode': 'numeric',
                    'maxlength': '10',
                    'pattern': r'\d{0,10}',
                }
            ),
            'id_expiry_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                }
            ),
            'id_image': forms.FileInput(
                attrs={'class': 'form-control'}
            ),
            'passport_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'inputmode': 'numeric',
                    'maxlength': str(OTHER_PASSPORT_NUMBER_MAX_LEN),
                }
            ),
            'passport_expiry_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                }
            ),
            'passport_image': forms.FileInput(
                attrs={'class': 'form-control'}
            ),
            'dl_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'inputmode': 'numeric',
                }
            ),
            'dl_expiry_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                }
            ),
            'dl_image': forms.FileInput(
                attrs={'class': 'form-control'}
            ),
            'card_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'inputmode': 'numeric',
                }
            ),
            'card_expiry_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                }
            ),
            'card_image': forms.FileInput(
                attrs={'class': 'form-control'}
            ),
            'mobile_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'inputmode': 'numeric',
                }
            ),
            'whatsapp_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'inputmode': 'numeric',
                }
            ),
            'whatsapp_same_as_mobile': forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # User account lookup (required, 1:1 at Driver level)
        self.fields.pop('user_account_id', None)
        instance_user = getattr(self.instance, 'user_account_id', None)
        base_users_qs = TenantUser.objects.filter(status=TenantUser.Status.ACTIVE)
        if instance_user and instance_user.pk:
            users_qs = (
                TenantUser.all_objects.filter(pk=instance_user.pk) | base_users_qs
            ).distinct().order_by('full_name')
        else:
            users_qs = base_users_qs.order_by('full_name')
        # Materialize once to avoid lazy server-side cursor issues at template render time.
        list(users_qs)
        self.fields['user_account_id'] = forms.ModelChoiceField(
            required=True,
            label=_('User account'),
            queryset=users_qs,
            empty_label=_('Select user...'),
            to_field_name='user_id',
            widget=forms.Select(attrs={'class': 'form-select'}),
        )
        self.fields['user_account_id'].label_from_instance = (
            lambda u: f'{u.full_name} ({u.username})'
        )
        if instance_user and instance_user.pk:
            self.fields['user_account_id'].initial = instance_user.pk

        # Truck assignment (optional; persisted via view after driver save)
        extra_truck_pks = []
        if self.is_bound:
            submitted_truck = (self.data.get('default_truck_id') or '').strip()
            if submitted_truck:
                extra_truck_pks.append(submitted_truck)
        trucks_qs = driver_default_truck_queryset(
            driver=self.instance if self.instance.pk else None,
            extra_truck_pks=extra_truck_pks,
        )
        # Materialize once to avoid lazy server-side cursor issues at template render time.
        list(trucks_qs)
        self.fields['default_truck_id'] = forms.ModelChoiceField(
            queryset=trucks_qs,
            required=False,
            label=_('Default truck'),
            empty_label=_('— Select Truck —'),
            widget=forms.Select(attrs={'class': 'form-select'}),
        )
        self.fields['default_truck_id'].label_from_instance = (
            lambda truck: f'{truck.truck_code} — {truck.plate_number}'
        )
        assigned_truck = driver_current_assigned_truck(self.instance)
        if assigned_truck:
            self.fields['default_truck_id'].initial = assigned_truck.pk

        self.fields.pop('nationality_country', None)
        country_pairs = self._build_country_choices()
        self.fields['nationality_country'] = PublicCountryChoiceField(
            address_instance=self.instance,
            country_fk_attr='nationality_country_id',
            choices=country_pairs,
            required=False,
            label=_('Nationality'),
            widget=forms.Select(attrs={'class': 'form-select'}),
        )
        nid = getattr(self.instance, 'nationality_country_id', None)
        if self.instance.pk and nid:
            self.fields['nationality_country'].initial = nid

        self.fields['vendor_account_id'].required = False
        self.fields['vendor_account_id'].initial = ''

        # Tenant UI: in-source only (no outsourced drivers in this product slice).
        self.fields['driver_source'].choices = [
            (DriverMaster.DriverSource.IN_SOURCE, _('In-Source')),
        ]
        self.fields['driver_source'].initial = DriverMaster.DriverSource.IN_SOURCE
        self.fields['arabic_name'].required = True
        self.fields['mobile_number'].required = True
        self.fields['driver_type'].required = False
        if self.instance.pk and getattr(self.instance, 'driver_type', '') == DriverMaster.DriverType.VENDOR:
            self.instance.driver_type = ''
        self.fields['driver_type'].choices = [
            ('', _('---------')),
        ] + [
            (value, label)
            for value, label in DriverMaster.DriverType.choices
            if value != DriverMaster.DriverType.VENDOR
        ]
        self.fields['english_name'].required = False
        self.fields['birth_date'].required = False

        for name in (
            'id_number',
            'id_expiry_date',
            'id_image',
            'passport_number',
            'passport_expiry_date',
            'passport_image',
            'dl_number',
            'dl_expiry_date',
            'dl_image',
            'card_number',
            'card_expiry_date',
            'card_image',
            'whatsapp_number',
        ):
            self.fields[name].required = False

    def _build_country_choices(self):
        with schema_context('public'):
            cid = getattr(self.instance, 'nationality_country_id', None)
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

    def clean(self):
        cleaned = super().clean()
        errors = {}

        selected_user = cleaned.get('user_account_id')
        if not selected_user:
            errors['user_account_id'] = _('User account is required.')
        else:
            uq = DriverMaster.objects.filter(user_account_id=selected_user)
            if self.instance.pk:
                uq = uq.exclude(pk=self.instance.pk)
            if uq.exists():
                errors['user_account_id'] = _(
                    'This user account is already linked to another driver.'
                )

        mobile = (cleaned.get('mobile_number') or '').strip()
        if mobile and not re.match(r'^\d+$', mobile):
            errors['mobile_number'] = _(
                'Mobile number must contain digits only'
            )

        wa = (cleaned.get('whatsapp_number') or '').strip()
        if wa and not re.match(r'^\d+$', wa):
            errors['whatsapp_number'] = _(
                'WhatsApp number must contain digits only'
            )

        id_num = (cleaned.get('id_number') or '').strip()
        if id_num and not re.match(r'^\d+$', id_num):
            errors['id_number'] = _('ID number must contain digits only')
        elif id_num and len(id_num) > SAUDI_DOCUMENT_NUMBER_MAX_LEN:
            errors['id_number'] = _(
                'ID number must be at most %(max)s digits'
            ) % {'max': SAUDI_DOCUMENT_NUMBER_MAX_LEN}

        nationality_code = _nationality_country_code(
            cleaned.get('nationality_country'),
        )
        passport_num = (cleaned.get('passport_number') or '').strip()
        passport_max = passport_number_max_len(nationality_code)
        if passport_num and not re.match(r'^\d+$', passport_num):
            errors['passport_number'] = _('Passport number must contain digits only')
        elif passport_num and len(passport_num) > passport_max:
            if nationality_code == SAUDI_COUNTRY_CODE:
                errors['passport_number'] = _(
                    'Passport number must be at most %(max)s digits for Saudi Arabia'
                ) % {'max': passport_max}
            else:
                errors['passport_number'] = _(
                    'Passport number must be at most %(max)s digits'
                ) % {'max': passport_max}

        def _check_digits_only(field_name, label):
            value = (cleaned.get(field_name) or '').strip()
            if value and not re.match(r'^\d+$', value):
                errors[field_name] = _(
                    '%(label)s must contain digits only'
                ) % {'label': label}

        _check_digits_only('dl_number', _('DL number'))
        _check_digits_only('card_number', _('Card number'))

        def _check_unique(field_name, value, label):
            if not value or not str(value).strip():
                return
            qs = DriverMaster.objects.filter(**{field_name: value})
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                errors[field_name] = _(
                    '%(label)s already exists for another driver'
                ) % {'label': label}

        _check_unique('id_number', id_num, _('ID number'))
        _check_unique(
            'passport_number',
            passport_num,
            _('Passport number'),
        )
        _check_unique(
            'dl_number',
            (cleaned.get('dl_number') or '').strip(),
            _('DL number'),
        )
        _check_unique(
            'card_number',
            (cleaned.get('card_number') or '').strip(),
            _('Card number'),
        )

        if cleaned.get('whatsapp_same_as_mobile'):
            cleaned['whatsapp_number'] = cleaned.get('mobile_number') or ''

        today = timezone.localdate()
        is_create = not self.instance.pk

        def _check_expiry(number, expiry, expiry_field, label):
            if not number or not str(number).strip():
                return
            if not expiry:
                return
            if is_create and expiry < today:
                errors[expiry_field] = _(
                    '%(label)s expiry date cannot be in the past'
                ) % {'label': label}

        _check_expiry(id_num, cleaned.get('id_expiry_date'), 'id_expiry_date', _('ID'))
        _check_expiry(
            passport_num,
            cleaned.get('passport_expiry_date'),
            'passport_expiry_date',
            _('Passport'),
        )
        _check_expiry(
            (cleaned.get('dl_number') or '').strip(),
            cleaned.get('dl_expiry_date'),
            'dl_expiry_date',
            _('Driving license'),
        )
        _check_expiry(
            (cleaned.get('card_number') or '').strip(),
            cleaned.get('card_expiry_date'),
            'card_expiry_date',
            _('Driver card'),
        )

        if errors:
            raise ValidationError(errors)

        cleaned['driver_source'] = DriverMaster.DriverSource.IN_SOURCE
        cleaned['vendor_account_id'] = ''

        if (cleaned.get('driver_type') or '').strip() == DriverMaster.DriverType.VENDOR:
            cleaned['driver_type'] = ''

        return cleaned
