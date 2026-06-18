from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from config.text_validators import ArabicTextFormMixin
from superadmin.models import Country
from tenant_workspace.models import DriverMaster, TruckMaster, TruckTypeMaster

from iroad_tenants.forms_tenant_address import PublicCountryChoiceField


class TruckMasterForm(ArabicTextFormMixin, forms.ModelForm):
    class Meta:
        model = TruckMaster
        fields = [
            'status',
            'sourcing_mode',
            'registration_country',
            'vendor_account_id',
            'is_vendor_same_as_owner',
            'owner_id',
            'owner_name',
            'operational_status',
            'plate_number',
            'saudi_plate_number',
            'saudi_english_letters',
            'saudi_arabic_letters',
            'non_saudi_plate_number',
            'plate_image',
            'truck_type',
            'chassis_number_vin',
            'serial_number',
            'color',
            'axle_count',
            'tires_count',
            'tare_weight_ton',
            'payload_capacity_ton',
            'gross_weight_ton',
            'volume_m3',
            'default_driver_id',
        ]
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'sourcing_mode': forms.HiddenInput(),
            'vendor_account_id': forms.HiddenInput(),
            'is_vendor_same_as_owner': forms.CheckboxInput(),
            'owner_id': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('Owner identifier')}
            ),
            'owner_name': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('Owner or company name')}
            ),
            'plate_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'readonly': True,
                    'placeholder': _('Auto-combined from plate fields'),
                }
            ),
            'saudi_plate_number': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('Numeric part')}
            ),
            'saudi_english_letters': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g. ABC',
                    'maxlength': '3',
                }
            ),
            'saudi_arabic_letters': forms.TextInput(
                attrs={
                    'class': 'form-control eal-arabic',
                    'placeholder': 'حروف عربية',
                    'dir': 'rtl',
                    'lang': 'ar',
                    'data-arabic-only': '1',
                }
            ),
            'non_saudi_plate_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('For non-KSA registered vehicles'),
                }
            ),
            'plate_image': forms.ClearableFileInput(
                attrs={'class': 'form-control', 'accept': 'image/*'}
            ),
            'truck_type': forms.Select(attrs={'class': 'form-select'}),
            'chassis_number_vin': forms.TextInput(
                attrs={'class': 'form-control', 'maxlength': '17', 'placeholder': '17-character VIN'}
            ),
            'serial_number': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('Manufacturer serial')}
            ),
            'color': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('e.g. White, Blue')}
            ),
            'axle_count': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g. 2, 3',
                    'min': '1',
                    'max': '10',
                    'step': '1',
                }
            ),
            'tires_count': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g. 6, 10',
                    'min': '1',
                    'max': '22',
                    'step': '1',
                }
            ),
            'tare_weight_ton': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.1',
                    'min': '0',
                    'placeholder': 'e.g. 8.5',
                }
            ),
            'payload_capacity_ton': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.1',
                    'min': '0',
                    'placeholder': 'e.g. 20',
                }
            ),
            'gross_weight_ton': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.1',
                    'min': '0',
                    'placeholder': 'e.g. 40',
                }
            ),
            'volume_m3': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.1',
                    'min': '0',
                    'placeholder': 'e.g. 60',
                }
            ),
            'default_driver_id': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields.pop('registration_country', None)
        country_pairs = self._build_country_choices()
        self.fields['registration_country'] = PublicCountryChoiceField(
            address_instance=self.instance,
            country_fk_attr='registration_country_id',
            choices=country_pairs,
            required=True,
            label=_('Registration Country'),
            widget=forms.Select(attrs={'class': 'form-select'}),
        )
        cid_val = getattr(self.instance, 'registration_country_id', None)
        if self.instance.pk and cid_val:
            self.fields['registration_country'].initial = cid_val

        tt = self.fields['truck_type']
        # Truck Type Master: only Active types in the dropdown (new trucks).
        # Editing: if this truck already uses an inactive type, keep that row visible.
        base_qs = TruckTypeMaster.active_objects.order_by('english_label', 'truck_type_code')
        instance_tt = getattr(self.instance, 'truck_type', None)
        if instance_tt and instance_tt.pk and instance_tt.status != TruckTypeMaster.Status.ACTIVE:
            tt.queryset = (
                TruckTypeMaster.objects.filter(pk=instance_tt.pk) | base_qs
            ).distinct().order_by('english_label', 'truck_type_code')
        else:
            tt.queryset = base_qs
        tt.empty_label = _('-Select type-')
        tt.required = True
        tt.label = _('Truck Type')

        def _truck_type_choice_label(obj: TruckTypeMaster) -> str:
            text = f'{obj.truck_type_code} — {obj.english_label}'
            if obj.status != TruckTypeMaster.Status.ACTIVE:
                text = f'{text} ({_("Inactive")})'
            return text

        tt.label_from_instance = _truck_type_choice_label

        self.fields['chassis_number_vin'].label = _('Chassis Number (VIN)')
        self.fields['serial_number'].label = _('Serial Number')

        # Link Truck -> Driver module: pick a driver from Driver Master.
        # If the truck currently points to an inactive driver, still include it in the dropdown.
        self.fields.pop('default_driver_id', None)
        instance_driver = getattr(self.instance, 'default_driver_id', None)
        base_qs = DriverMaster.active_objects.all()
        if instance_driver and instance_driver.pk:
            queryset = (DriverMaster.objects.filter(pk=instance_driver.pk) | base_qs).distinct()
        else:
            queryset = base_qs

        self.fields['default_driver_id'] = forms.ModelChoiceField(
            queryset=queryset.order_by('driver_code'),
            required=False,
            label=_('Default Driver'),
            empty_label=_('— Select Driver —'),
            widget=forms.Select(attrs={'class': 'form-select'}),
        )
        if instance_driver and instance_driver.pk:
            self.fields['default_driver_id'].initial = instance_driver.pk

        # Sourcing / vendor are not shown on the tenant form UI; keep DB compatibility.
        # Hidden field: do not use required=True — a missing POST key surfaces as an orphan
        # "This field is required." above the layout. Default is applied in clean().
        self.fields['sourcing_mode'].required = False
        if not self.instance.pk:
            self.fields['sourcing_mode'].initial = TruckMaster.SourcingMode.IN_SOURCE

        self.fields['vendor_account_id'].required = False
        # Hidden vendor field: validate length in clean() so errors can be shown on Owner ID.
        self.fields['vendor_account_id'] = forms.CharField(
            required=False,
            widget=forms.HiddenInput(),
        )

        self.fields.pop('operational_status', None)
        self.fields['operational_status'] = forms.ChoiceField(
            choices=[('', _('-Select status-'))]
            + list(TruckMaster.OperationalStatus.choices),
            required=False,
            label=_('Operational Status'),
            widget=forms.Select(attrs={'class': 'form-select'}),
        )
        if self.instance.pk:
            self.fields['operational_status'].initial = (
                self.instance.operational_status or ''
            )

        self.fields['owner_id'].label = _('Owner ID')
        self.fields['owner_name'].label = _('Owner Name')
        self.fields['is_vendor_same_as_owner'].label = _(
            'Is Company info as same Owner Info'
        )

        self.fields['axle_count'].label = _('Axle Count')
        self.fields['tires_count'].label = _('Tires Count')
        self.fields['tare_weight_ton'].label = _('Tare Weight (Ton)')
        self.fields['payload_capacity_ton'].label = _('Payload Capacity (Ton)')
        self.fields['gross_weight_ton'].label = _('Gross Weight (Ton)')
        self.fields['volume_m3'].label = _('Volume (m³)')

        self.fields['plate_number'].required = False
        self.fields['plate_number'].label = _('Plate Number')

        self.fields['saudi_plate_number'].label = _('Saudi Plate Number')
        self.fields['saudi_english_letters'].label = _('Saudi English Letters')
        self.fields['saudi_arabic_letters'].label = _('Saudi Arabic Letters')
        self.fields['non_saudi_plate_number'].label = _('Non-Saudi Plate Number')

        for name in (
            'saudi_plate_number',
            'saudi_english_letters',
            'saudi_arabic_letters',
            'non_saudi_plate_number',
        ):
            self.fields[name].required = False

    def add_model_validation_errors(self, error_dict):
        """Map hidden-field model errors onto visible form fields."""
        for field_name, errs in error_dict.items():
            target = field_name
            if field_name == 'vendor_account_id' and self.data.get(
                'is_vendor_same_as_owner'
            ):
                target = 'owner_id'
            for err in errs:
                self.add_error(target, err)

    def _build_country_choices(self):
        with schema_context('public'):
            cid = getattr(self.instance, 'registration_country_id', None)
            if cid:
                qs = (
                    Country.objects.filter(Q(is_active=True) | Q(pk=cid))
                    .distinct()
                    .order_by('name_en')
                )
            else:
                qs = Country.objects.filter(is_active=True).order_by('name_en')
            rows = list(qs)
        return [('', _('-Select country-'))] + [
            (c.country_code, f'{c.country_code} — {c.name_en}') for c in rows
        ]

    def clean(self):
        cleaned = super().clean()
        sm = cleaned.get('sourcing_mode')
        if sm in (None, ''):
            cleaned['sourcing_mode'] = TruckMaster.SourcingMode.IN_SOURCE
        else:
            cleaned['sourcing_mode'] = str(sm).strip()

        if cleaned.get('is_vendor_same_as_owner'):
            owner_id = (cleaned.get('owner_id') or '').strip()
            cleaned['vendor_account_id'] = owner_id
            if len(owner_id) > 64:
                raise ValidationError(
                    {
                        'owner_id': _(
                            'Owner ID must be at most 64 characters when vendor is the same as owner.'
                        )
                    }
                )

        country = cleaned.get('registration_country')
        vendor_raw = (cleaned.get('vendor_account_id') or '').strip()
        cleaned['vendor_account_id'] = vendor_raw

        if vendor_raw and len(vendor_raw) > 64:
            field_name = (
                'owner_id'
                if cleaned.get('is_vendor_same_as_owner')
                else 'vendor_account_id'
            )
            raise ValidationError(
                {field_name: _('This value must be at most 64 characters.')}
            )

        if (
            str(cleaned.get('sourcing_mode') or '')
            == str(TruckMaster.SourcingMode.OUT_SOURCE)
            and not (vendor_raw or '').strip()
        ):
            raise ValidationError(
                {'vendor_account_id': _('Vendor account is required for Out-Source trucks')}
            )

        cc = getattr(country, 'country_code', None) or getattr(country, 'pk', None)
        cc = str(cc).strip().upper() if cc is not None else ''

        sp = (cleaned.get('saudi_plate_number') or '').strip()

        if cc == 'SA':
            if not sp:
                raise ValidationError(
                    {'saudi_plate_number': _('Saudi plate number is required')}
                )
            english_letters = (cleaned.get('saudi_english_letters') or '').strip().upper()
            cleaned['saudi_english_letters'] = english_letters
            if not english_letters:
                raise ValidationError(
                    {
                        'saudi_english_letters': _(
                            'Saudi English letters are required'
                        )
                    }
                )
            if not (cleaned.get('saudi_arabic_letters') or '').strip():
                raise ValidationError(
                    {
                        'saudi_arabic_letters': _(
                            'Saudi Arabic letters are required'
                        )
                    }
                )
            cleaned['plate_number'] = f'{sp} {english_letters}'.strip()
            cleaned['non_saudi_plate_number'] = ''

        elif cc:
            nons = (cleaned.get('non_saudi_plate_number') or '').strip()
            if not nons:
                raise ValidationError(
                    {'non_saudi_plate_number': _('Plate number is required')}
                )
            cleaned['plate_number'] = nons
            cleaned['saudi_plate_number'] = ''
            cleaned['saudi_english_letters'] = ''
            cleaned['saudi_arabic_letters'] = ''

        plate = (cleaned.get('plate_number') or '').strip()
        if country is not None and plate:
            q = TruckMaster.objects.filter(
                plate_number=plate,
                registration_country=country,
            )
            if self.instance.pk:
                q = q.exclude(pk=self.instance.pk)
            if q.exists():
                raise ValidationError(
                    {
                        'plate_number': _('This plate number is already registered for this country')
                    }
                )

        vin = (cleaned.get('chassis_number_vin') or '').strip()
        if vin:
            q = TruckMaster.objects.filter(chassis_number_vin__iexact=vin)
            if self.instance.pk:
                q = q.exclude(pk=self.instance.pk)
            if q.exists():
                raise ValidationError(
                    {'chassis_number_vin': _('This chassis/VIN number already exists')}
                )

        payload = cleaned.get('payload_capacity_ton')
        gross = cleaned.get('gross_weight_ton')
        if payload is not None and gross is not None:
            if payload > gross:
                raise ValidationError(
                    {
                        'payload_capacity_ton': _(
                            'Payload capacity cannot exceed gross weight'
                        )
                    }
                )

        return cleaned
