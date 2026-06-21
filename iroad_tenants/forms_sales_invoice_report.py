from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from iroad_tenants.tenant_form_choices import pin_model_choice_field
from superadmin.models import Currency
from tenant_workspace.models import (
    SalesInvoiceReport,
    SalesInvoiceReportBooking,
    SalesInvoiceReportShipment,
    SalesInvoiceReportSurcharge,
    TenantClientAccount,
)


def _sir_form_valid_currency_code(currency_code):
    code = (currency_code or '').strip().upper()
    if code and Currency.objects.filter(currency_code=code, is_active=True).exists():
        return code
    return (
        Currency.objects.filter(is_active=True)
        .order_by('currency_code')
        .values_list('currency_code', flat=True)
        .first()
        or 'SAR'
    )


class SalesInvoiceReportForm(forms.ModelForm):
    class Meta:
        model = SalesInvoiceReport
        fields = [
            'report_no',
            'client',
            'report_date',
            'booking_date_from',
            'booking_date_to',
            'currency',
            'total_freight_amount',
            'total_surcharge_amount',
            'status',
            'sales_invoice_ref',
            'remarks',
        ]
        widgets = {
            'report_no': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'client': forms.Select(attrs={'class': 'form-select'}),
            'report_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'booking_date_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'booking_date_to': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'currency': forms.TextInput(attrs={'class': 'form-control'}),
            'total_freight_amount': forms.NumberInput(
                attrs={'class': 'form-control', 'readonly': 'readonly', 'step': '0.01'}
            ),
            'total_surcharge_amount': forms.NumberInput(
                attrs={'class': 'form-control', 'readonly': 'readonly', 'step': '0.01'}
            ),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'sales_invoice_ref': forms.TextInput(attrs={'class': 'form-control'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        client_field = self.fields['client']
        client_field.queryset = TenantClientAccount.objects.filter(
            status=TenantClientAccount.Status.ACTIVE,
        ).order_by('display_name')
        client_field.empty_label = _('Select client...')
        client_field.label_from_instance = (
            lambda obj: f'{obj.account_no} - {obj.display_name}'
        )
        pin_model_choice_field(client_field, list(client_field.queryset))

        # Derived/system fields
        self.fields['report_no'].required = False
        self.fields['total_freight_amount'].required = False
        self.fields['total_surcharge_amount'].required = False
        self.fields['total_freight_amount'].disabled = True
        self.fields['total_surcharge_amount'].disabled = True
        self.fields['currency'].required = False
        if not self.initial.get('currency') and not getattr(self.instance, 'currency', ''):
            self.fields['currency'].initial = 'SAR'

        # Sales invoice relation is optional until target model exists.
        self.fields['sales_invoice_ref'].required = False

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and self.instance.is_fully_locked:
            raise ValidationError(_('Converted reports are fully locked and cannot be edited.'))
        if cleaned.get('booking_date_from') and cleaned.get('booking_date_to'):
            if cleaned['booking_date_from'] > cleaned['booking_date_to']:
                raise ValidationError({'booking_date_to': _('Booking To must be on/after Booking From.')})
        cleaned['currency'] = _sir_form_valid_currency_code(cleaned.get('currency') or '')
        client = cleaned.get('client')
        if client and not (self.data.get('currency') or '').strip():
            preferred = (getattr(client, 'preferred_currency', '') or '').strip().upper()
            cleaned['currency'] = _sir_form_valid_currency_code(preferred or cleaned['currency'])
        return cleaned


class SalesInvoiceReportBookingForm(forms.ModelForm):
    class Meta:
        model = SalesInvoiceReportBooking
        fields = [
            'line_no',
            'booking',
            'so_ref',
            'service_name',
            'trip_type',
            'sell_price',
            'booking_status',
        ]
        widgets = {
            'line_no': forms.NumberInput(attrs={'class': 'form-control'}),
            'booking': forms.HiddenInput(),
            'so_ref': forms.TextInput(attrs={'class': 'form-control'}),
            'service_name': forms.TextInput(attrs={'class': 'form-control'}),
            'trip_type': forms.TextInput(attrs={'class': 'form-control'}),
            'sell_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'booking_status': forms.TextInput(attrs={'class': 'form-control'}),
        }


class SalesInvoiceReportSurchargeForm(forms.ModelForm):
    class Meta:
        model = SalesInvoiceReportSurcharge
        fields = [
            'line_no',
            'surcharge',
            'booking',
            'shipment',
            'surcharge_type',
            'service_name',
            'amount',
        ]
        widgets = {
            'line_no': forms.NumberInput(attrs={'class': 'form-control'}),
            'surcharge': forms.HiddenInput(),
            'booking': forms.HiddenInput(),
            'shipment': forms.HiddenInput(),
            'surcharge_type': forms.TextInput(attrs={'class': 'form-control'}),
            'service_name': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


class SalesInvoiceReportShipmentForm(forms.ModelForm):
    class Meta:
        model = SalesInvoiceReportShipment
        fields = [
            'line_no',
            'shipment',
            'booking',
            'shipment_date',
            'from_location',
            'to_location',
            'truck_plate',
            'customer_ref_docs',
            'pod_date',
            'pod_status',
        ]
        widgets = {
            'line_no': forms.NumberInput(attrs={'class': 'form-control'}),
            'shipment': forms.HiddenInput(),
            'booking': forms.HiddenInput(),
            'shipment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'from_location': forms.TextInput(attrs={'class': 'form-control'}),
            'to_location': forms.TextInput(attrs={'class': 'form-control'}),
            'truck_plate': forms.TextInput(attrs={'class': 'form-control'}),
            'customer_ref_docs': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'pod_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'pod_status': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
        }
