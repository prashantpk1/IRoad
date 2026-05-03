from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from superadmin.models import Country
from tenant_workspace.models import TenantLocationMaster


class TenantLocationMasterForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        allow_inactive_status = bool(kwargs.pop('allow_inactive_status', False))
        super().__init__(*args, **kwargs)
        self.fields['country'].queryset = Country.objects.filter(is_active=True).order_by('name_en')
        self.fields['country'].empty_label = _('Select country')
        self.fields['country'].label_from_instance = lambda c: c.name_en
        if allow_inactive_status:
            self.fields['status'].choices = TenantLocationMaster.Status.choices
        else:
            self.fields['status'].choices = [
                (TenantLocationMaster.Status.ACTIVE, _('Active')),
            ]
        self.initial.setdefault('location_type', TenantLocationMaster.LocationType.CITY)
        self.initial.setdefault('status', TenantLocationMaster.Status.ACTIVE)
        self.initial.setdefault('is_serviceable', True)
        self._allow_inactive_status = allow_inactive_status

    class Meta:
        model = TenantLocationMaster
        fields = (
            'country',
            'province',
            'location_name_arabic',
            'location_name_english',
            'display_label',
            'location_type',
            'status',
            'is_serviceable',
        )
        widgets = {
            'country': forms.Select(attrs={'class': 'form-select', 'id': 'country'}),
            'province': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'id': 'province',
                    'placeholder': _('Province / State'),
                }
            ),
            'location_name_arabic': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'id': 'locationNameArabic',
                    'placeholder': _('Location Name'),
                    'dir': 'rtl',
                }
            ),
            'location_name_english': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'id': 'locationNameEnglish',
                    'placeholder': _('Location Name'),
                }
            ),
            'display_label': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'id': 'displayLabel',
                    'placeholder': _('Short label for dropdowns'),
                }
            ),
            'location_type': forms.Select(
                attrs={'class': 'form-select', 'id': 'locationType'}
            ),
            'status': forms.Select(attrs={'class': 'form-select', 'id': 'status'}),
            'is_serviceable': forms.CheckboxInput(
                attrs={'id': 'isServiceable'}
            ),
        }

    def clean_status(self):
        status = self.cleaned_data.get('status')
        if not self._allow_inactive_status and status != TenantLocationMaster.Status.ACTIVE:
            raise ValidationError(_('Inactive is not allowed during create.'))
        return status

