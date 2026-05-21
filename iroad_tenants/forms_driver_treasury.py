from django import forms
from django.core.exceptions import ValidationError

from iroad_tenants.driver_treasury_ops import (
    validate_shipment_for_treasury,
    validate_transaction_type_category,
)
from tenant_workspace.models import (
    DriverTreasury,
    DriverTreasuryTransaction,
    DriverMaster,
    TenantShipment,
)


class DriverTreasuryForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only Active drivers selectable
        self.fields['driver'].queryset = (
            DriverMaster.active_objects.all()
        )
        self.fields['driver'].empty_label = (
            '— Select Driver —'
        )
        # current_balance is read-only — never in form
        # treasury_code is auto-generated — never in form

    class Meta:
        model = DriverTreasury
        fields = ['driver', 'status']
        widgets = {
            'driver': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'status': forms.Select(
                attrs={'class': 'form-select'}
            ),
        }

    def clean_driver(self):
        driver = self.cleaned_data.get('driver')
        if not driver:
            raise forms.ValidationError(
                'Driver is required'
            )
        if not self.instance.pk:
            if DriverTreasury.objects.filter(
                driver=driver,
                status=DriverTreasury.Status.ACTIVE,
            ).exists():
                raise forms.ValidationError(
                    'This driver already has an active treasury wallet. '
                    'Edit the existing treasury or set it inactive first.'
                )
        return driver


class DriverTreasuryTransactionForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['driver_treasury'].queryset = (
            DriverTreasury.active_objects.select_related('driver')
        )
        self.fields['driver_treasury'].empty_label = '— Select Treasury —'
        self.fields['shipment'].queryset = (
            TenantShipment.objects.select_related('driver')
            .order_by('-shipment_date', '-created_at')
        )
        self.fields['shipment'].empty_label = '— None —'
        self.fields['shipment'].label_from_instance = (
            lambda obj: obj.shipment_no
        )

    class Meta:
        model = DriverTreasuryTransaction
        fields = [
            'transaction_date',
            'driver_treasury',
            'transaction_type',
            'transaction_category',
            'amount',
            'shipment',
            'description',
        ]
        widgets = {
            'transaction_date': forms.DateTimeInput(
                attrs={
                    'class': 'form-control',
                    'type': 'datetime-local',
                }
            ),
            'driver_treasury': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'transaction_type': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'transaction_category': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'amount': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'min': '0',
                    'step': '0.01',
                }
            ),
            'shipment': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'description': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                }
            ),
        }

    def clean(self):
        cleaned = super().clean()
        txn_type = cleaned.get('transaction_type')
        txn_category = cleaned.get('transaction_category')
        if txn_type and txn_category:
            try:
                validate_transaction_type_category(txn_type, txn_category)
            except ValidationError as exc:
                if hasattr(exc, 'error_dict'):
                    for field, msgs in exc.error_dict.items():
                        self.add_error(field, msgs)
                else:
                    self.add_error(None, exc)
        try:
            validate_shipment_for_treasury(
                cleaned.get('shipment'),
                cleaned.get('driver_treasury'),
            )
        except ValidationError as exc:
            if hasattr(exc, 'error_dict'):
                for field, msgs in exc.error_dict.items():
                    self.add_error(field, msgs)
            else:
                self.add_error('shipment', exc)
        return cleaned

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount < 0:
            raise forms.ValidationError(
                'Amount must be 0 or greater'
            )
        if amount is not None and amount == 0:
            raise forms.ValidationError(
                'Amount must be greater than zero'
            )
        return amount

    def clean_transaction_date(self):
        dt = self.cleaned_data.get('transaction_date')
        if not dt:
            raise forms.ValidationError(
                'Transaction date is required'
            )
        return dt
