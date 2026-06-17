from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from tenant_workspace.models import TenantServiceItemCategory


class TenantServiceItemCategoryForm(forms.ModelForm):
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
        model = TenantServiceItemCategory
        fields = ('name_english', 'name_arabic', 'status')
        widgets = {
            'name_english': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': _('e.g. Loading Service')}
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
            self.initial.setdefault('status', TenantServiceItemCategory.Status.ACTIVE)
        else:
            self.fields['category_code_preview'].initial = self.instance.category_code
        self.fields['status'].choices = TenantServiceItemCategory.Status.choices
        self.fields['name_english'].required = True
        self.fields['name_arabic'].required = True
        self.fields['status'].required = True

    def clean_name_arabic(self):
        value = (self.cleaned_data.get('name_arabic') or '').strip()
        if not value:
            raise ValidationError(_('Arabic name is required.'))
        return value
