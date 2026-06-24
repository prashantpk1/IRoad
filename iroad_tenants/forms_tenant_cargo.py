from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from config.text_validators import ArabicTextFormMixin
from tenant_workspace.models import (
    TenantCargoCategory,
    TenantCargoMaster,
    TenantClientAccount,
)

CARGO_UOM_CHOICES = [
    ('', _('Select UOM')),
    ('Boxes', _('Boxes')),
    ('Pallets', _('Pallets')),
    ('Kilograms', _('Kilograms')),
    ('Pieces', _('Pieces')),
]

_CARGO_UOM_ALIASES = {
    'box': 'Boxes',
    'boxs': 'Boxes',
    'boxes': 'Boxes',
    'pallet': 'Pallets',
    'pallets': 'Pallets',
    'kg': 'Kilograms',
    'kilogram': 'Kilograms',
    'kilograms': 'Kilograms',
    'piece': 'Pieces',
    'pieces': 'Pieces',
    'pcs': 'Pieces',
    'place': 'Pieces',
    'places': 'Pieces',
}


def normalize_cargo_uom(value: str) -> str:
    """Map legacy / mistyped UOM text to canonical cargo-master choices."""
    stripped = (value or '').strip()
    if not stripped:
        return ''
    valid = {choice[0] for choice in CARGO_UOM_CHOICES if choice[0]}
    if stripped in valid:
        return stripped
    return _CARGO_UOM_ALIASES.get(stripped.casefold(), stripped)


class TenantCargoCategoryForm(ArabicTextFormMixin, forms.ModelForm):
    category_code_preview = forms.CharField(
        label=_('Category Code'),
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
        model = TenantCargoCategory
        fields = ('name_english', 'name_arabic', 'status')
        widgets = {
            'name_english': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('e.g. Electronics')}
            ),
            'name_arabic': forms.TextInput(
                attrs={
                    'class': 'form-control eal-arabic',
                    'dir': 'rtl',
                    'lang': 'ar',
                    'placeholder': _('Arabic name'),
                }
            ),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields.pop('category_code_preview', None)
            self.initial.setdefault('status', TenantCargoCategory.Status.ACTIVE)
        else:
            self.fields['category_code_preview'].initial = self.instance.category_code
        self.fields['status'].choices = TenantCargoCategory.Status.choices
        self.fields['name_english'].required = True
        self.fields['name_arabic'].required = True
        self.fields['status'].required = True

    def clean_name_arabic(self):
        value = (self.cleaned_data.get('name_arabic') or '').strip()
        if not value:
            raise ValidationError(_('Arabic name is required.'))
        return value


class TenantCargoMasterForm(ArabicTextFormMixin, forms.ModelForm):
    cargo_code_preview = forms.CharField(
        label=_('Cargo Code'),
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
        model = TenantCargoMaster
        fields = (
            'client_account',
            'display_name',
            'arabic_label',
            'english_label',
            'cargo_category',
            'client_sku_external_ref',
            'uom',
            'weight_per_unit',
            'volume_per_unit',
            'length',
            'width',
            'height',
            'refrigerated_goods',
            'min_temp',
            'max_temp',
            'dangerous_goods',
            'notes',
            'status',
        )
        labels = {
            'uom': _('UOM (Unit of Measure)'),
            'weight_per_unit': _('Weight per Unit (kg)'),
            'volume_per_unit': _('Volume per Unit (m³)'),
            'length': _('Length (m)'),
            'width': _('Width (m)'),
            'height': _('Height (m)'),
            'min_temp': _('Min Temp (°C)'),
            'max_temp': _('Max Temp (°C)'),
        }
        widgets = {
            'client_account': forms.Select(attrs={'class': 'form-select'}),
            'display_name': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('e.g. Premium Widgets')}
            ),
            'arabic_label': forms.TextInput(
                attrs={
                    'class': 'form-control eal-arabic',
                    'dir': 'rtl',
                    'lang': 'ar',
                    'data-arabic-only': '1',
                    'placeholder': _('Arabic label'),
                }
            ),
            'english_label': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('English label')}
            ),
            'cargo_category': forms.Select(attrs={'class': 'form-select'}),
            'client_sku_external_ref': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('e.g. SKU-12345')}
            ),
            'weight_per_unit': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': '0',
                    'placeholder': '0.00',
                }
            ),
            'volume_per_unit': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': '0',
                    'placeholder': '0.00',
                }
            ),
            'length': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': '0',
                    'placeholder': '0.00',
                }
            ),
            'width': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': '0',
                    'placeholder': '0.00',
                }
            ),
            'height': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'min': '0',
                    'placeholder': '0.00',
                }
            ),
            'refrigerated_goods': forms.CheckboxInput(
                attrs={'class': 'form-check-input', 'id': 'refrigeratedGoods'}
            ),
            'min_temp': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'placeholder': _('E.g., -18'),
                }
            ),
            'max_temp': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'placeholder': _('E.g., 4'),
                }
            ),
            'dangerous_goods': forms.CheckboxInput(
                attrs={'class': 'form-check-input', 'id': 'dangerousGoods'}
            ),
            'notes': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': _('Enter any additional instructions or remarks...'),
                }
            ),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields.pop('cargo_code_preview', None)
            self.initial.setdefault('status', TenantCargoMaster.Status.ACTIVE)
            self.initial.setdefault('refrigerated_goods', False)
            self.initial.setdefault('dangerous_goods', False)
        else:
            self.fields['cargo_code_preview'].initial = self.instance.cargo_code

        self.fields['status'].choices = TenantCargoMaster.Status.choices
        self.fields['client_account'].empty_label = _('- Select client -')
        active_clients = TenantClientAccount.objects.filter(
            status=TenantClientAccount.Status.ACTIVE,
        ).order_by('display_name')
        self.fields['client_account'].queryset = active_clients
        self.fields['client_account'].label_from_instance = (
            lambda obj: f'{obj.account_no} — {obj.display_name}'
        )

        cat_qs = TenantCargoCategory.objects.filter(
            status=TenantCargoCategory.Status.ACTIVE,
        ).order_by('name_english')
        if self.instance and getattr(self.instance, 'cargo_category_id', None):
            cat_qs = TenantCargoCategory.objects.filter(
                Q(status=TenantCargoCategory.Status.ACTIVE)
                | Q(pk=self.instance.cargo_category_id)
            ).order_by('name_english')
        self.fields['cargo_category'].queryset = cat_qs
        self.fields['cargo_category'].empty_label = _('- Select category -')
        self.fields['cargo_category'].label_from_instance = (
            lambda obj: f'{obj.category_code} — {obj.name_english}'
        )

        uom_choices = list(CARGO_UOM_CHOICES)
        current_uom = ''
        if self.instance.pk:
            current_uom = normalize_cargo_uom(self.instance.uom or '')
        if self.is_bound:
            current_uom = normalize_cargo_uom(
                self.data.get(self.add_prefix('uom')) or current_uom or '',
            )
        valid_uom_keys = {value for value, _ in uom_choices if value}
        if current_uom and current_uom not in valid_uom_keys:
            uom_choices.append((current_uom, current_uom))
        self.fields['uom'] = forms.ChoiceField(
            choices=uom_choices,
            required=True,
            label=_('UOM (Unit of Measure)'),
            widget=forms.Select(attrs={'class': 'form-select'}),
        )
        if current_uom:
            self.fields['uom'].initial = current_uom

    def clean_uom(self):
        uom = normalize_cargo_uom(self.cleaned_data.get('uom') or '')
        if not uom:
            raise ValidationError(_('Select a unit of measure.'))
        return uom

    def clean_client_account(self):
        acc = self.cleaned_data.get('client_account')
        if not acc:
            return acc
        if acc.status != TenantClientAccount.Status.ACTIVE:
            if self.instance.pk and self.instance.client_account_id == acc.pk:
                return acc
            raise ValidationError(_('Select an active client account.'))
        return acc

    def clean_cargo_category(self):
        cat = self.cleaned_data.get('cargo_category')
        if not cat:
            return cat
        if cat.status != TenantCargoCategory.Status.ACTIVE:
            if self.instance.pk and self.instance.cargo_category_id == cat.pk:
                return cat
            raise ValidationError(_('Select an active cargo category.'))
        return cat

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('refrigerated_goods'):
            cleaned['min_temp'] = None
            cleaned['max_temp'] = None
        return cleaned
