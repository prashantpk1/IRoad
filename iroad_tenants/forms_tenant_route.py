from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from tenant_workspace.models import TenantLocationMaster, TenantRouteMaster


class TenantRouteMasterForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        allow_inactive_status = bool(kwargs.pop('allow_inactive_status', False))
        super().__init__(*args, **kwargs)
        location_qs = TenantLocationMaster.active_serviceable_objects.select_related('country').order_by(
            'display_label'
        )
        self.fields['origin_point'].queryset = location_qs
        self.fields['destination_point'].queryset = location_qs
        self.fields['origin_point'].empty_label = _('Select origin location')
        self.fields['destination_point'].empty_label = _('Select destination location')
        if allow_inactive_status:
            self.fields['status'].choices = TenantRouteMaster.Status.choices
        else:
            self.fields['status'].choices = [
                (TenantRouteMaster.Status.ACTIVE, _('Active')),
            ]
        self.initial.setdefault('route_type', TenantRouteMaster.RouteType.DOMESTIC)
        self.initial.setdefault('status', TenantRouteMaster.Status.ACTIVE)
        self._allow_inactive_status = allow_inactive_status

    class Meta:
        model = TenantRouteMaster
        fields = (
            'route_label',
            'route_type',
            'origin_point',
            'destination_point',
            'status',
            'distance_km',
            'estimated_duration_h',
            'has_customs',
            'has_toll_gates',
        )
        widgets = {
            'route_label': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'id': 'routeLabel',
                    'placeholder': _('Riyadh – Jeddah'),
                }
            ),
            'route_type': forms.Select(attrs={'class': 'form-select', 'id': 'routeType'}),
            'origin_point': forms.Select(attrs={'class': 'form-select', 'id': 'originPoint'}),
            'destination_point': forms.Select(
                attrs={'class': 'form-select', 'id': 'destinationPoint'}
            ),
            'status': forms.Select(attrs={'class': 'form-select', 'id': 'status'}),
            'distance_km': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'id': 'distanceKm',
                    'placeholder': '0',
                    'min': '0',
                    'step': '0.1',
                }
            ),
            'estimated_duration_h': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'id': 'estimatedDurationH',
                    'placeholder': '0',
                    'min': '0',
                    'step': '0.5',
                }
            ),
            'has_customs': forms.CheckboxInput(attrs={'id': 'hasCustoms'}),
            'has_toll_gates': forms.CheckboxInput(attrs={'id': 'hasTollGates'}),
        }

    def clean_status(self):
        status = self.cleaned_data.get('status')
        if not self._allow_inactive_status and status != TenantRouteMaster.Status.ACTIVE:
            raise ValidationError(_('Inactive is not allowed during create.'))
        return status
