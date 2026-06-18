from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from config.text_validators import ArabicTextFormMixin
from tenant_workspace.models import TruckTypeMaster


class TruckTypeMasterForm(ArabicTextFormMixin, forms.ModelForm):
    """TRT-001 — ``truck_type_code`` is never a form field; allocated on create only."""

    truck_type_code_preview = forms.CharField(
        label=_('Truck Type Code'),
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
        model = TruckTypeMaster
        fields = ('english_label', 'arabic_label', 'status')
        widgets = {
            'english_label': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('e.g. Flatbed'),
                }
            ),
            'arabic_label': forms.TextInput(
                attrs={
                    'class': 'form-control eal-arabic',
                    'dir': 'rtl',
                    'lang': 'ar',
                    'data-arabic-only': '1',
                    'placeholder': _('مثال: مسطح'),
                }
            ),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields.pop('truck_type_code_preview', None)
            self.initial.setdefault('status', TruckTypeMaster.Status.ACTIVE)
        else:
            self.fields['truck_type_code_preview'].initial = self.instance.truck_type_code
        self.fields['status'].choices = TruckTypeMaster.Status.choices

    def clean_english_label(self):
        v = (self.cleaned_data.get('english_label') or '').strip()
        if not v:
            raise ValidationError(_('English label is required.'))
        if len(v) > 200:
            raise ValidationError(_('English label must be at most 200 characters.'))
        return v

    def clean_arabic_label(self):
        v = (self.cleaned_data.get('arabic_label') or '').strip()
        if not v:
            raise ValidationError(_('Arabic label is required.'))
        if len(v) > 200:
            raise ValidationError(_('Arabic label must be at most 200 characters.'))
        return v

    def clean_status(self):
        s = (self.cleaned_data.get('status') or '').strip()
        allowed = {TruckTypeMaster.Status.ACTIVE, TruckTypeMaster.Status.INACTIVE}
        if s not in allowed:
            raise ValidationError(_('Status must be Active or Inactive.'))
        return s
