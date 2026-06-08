from django import forms
from django.core.exceptions import ValidationError

from tenant_workspace.models import TruckSettings


class TruckSettingsForm(forms.ModelForm):
    class Meta:
        model = TruckSettings
        fields = [
            'default_truck_status',
            'maintenance_reminder_days',
            'insurance_expiry_alert_days',
            'fuel_consumption_tracking_enabled',
        ]
        widgets = {
            'default_truck_status': forms.Select(attrs={'class': 'form-select'}),
            'maintenance_reminder_days': forms.NumberInput(
                attrs={'class': 'form-control has-icon', 'min': 0, 'max': 365}
            ),
            'insurance_expiry_alert_days': forms.NumberInput(
                attrs={'class': 'form-control has-icon', 'min': 0, 'max': 180}
            ),
            'fuel_consumption_tracking_enabled': forms.CheckboxInput(),
        }

    def clean_maintenance_reminder_days(self):
        val = self.cleaned_data.get('maintenance_reminder_days')
        if val is not None and not (0 <= val <= 365):
            raise ValidationError('Must be between 0 and 365')
        return val

    def clean_insurance_expiry_alert_days(self):
        val = self.cleaned_data.get('insurance_expiry_alert_days')
        if val is not None and not (0 <= val <= 180):
            raise ValidationError('Must be between 0 and 180')
        return val

