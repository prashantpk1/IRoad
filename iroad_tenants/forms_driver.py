import os

from django import forms
from django.core.exceptions import ValidationError

from config.text_validators import ArabicTextFormMixin
from tenant_workspace.models import DriverAttachment, DriverSettings

_ALLOWED_EXT = frozenset(
    {'.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx'}
)
_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class DriverAttachmentForm(ArabicTextFormMixin, forms.ModelForm):
    class Meta:
        model = DriverAttachment
        fields = [
            'arabic_label',
            'english_label',
            'doc_ref_number',
            'attachment_date',
            'is_expiry_applicable',
            'expiry_date',
            'record_status',
            'attachment_file',
            'file_notes',
        ]
        widgets = {
            'arabic_label': forms.TextInput(
                attrs={
                    'class': 'form-control eal-arabic',
                    'placeholder': 'Enter Arabic label',
                    'dir': 'rtl',
                    'lang': 'ar',
                    'data-arabic-only': '1',
                }
            ),
            'english_label': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter English label',
                }
            ),
            'doc_ref_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter document reference number',
                }
            ),
            'attachment_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                }
            ),
            'is_expiry_applicable': forms.CheckboxInput(),
            'expiry_date': forms.DateInput(
                attrs={
                    'class': 'form-control',
                    'type': 'date',
                }
            ),
            'record_status': forms.Select(
                attrs={'class': 'form-select'},
            ),
            'attachment_file': forms.FileInput(
                attrs={'class': 'form-control'}
            ),
            'file_notes': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': (
                        'Describe this document...'
                    ),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.attachment_file:
                self.fields[
                    'attachment_file'
                ].required = False
                self.fields[
                    'attachment_file'
                ].help_text = (
                    'Leave empty to keep current file.'
                )

        rs = self.fields['record_status']
        rs.choices = [
            ('', '-Select status-'),
        ] + list(DriverAttachment.RecordStatus.choices)
        rs.required = True
        rs.widget.attrs.setdefault('class', 'form-select')
        rs.help_text = 'Current status of the attachment'

    def clean_file_notes(self):
        notes = self.cleaned_data.get(
            'file_notes', ''
        ).strip()
        if not notes:
            raise ValidationError(
                'File notes are required'
            )
        return notes

    def clean_attachment_file(self):
        file = self.cleaned_data.get('attachment_file')
        if not file:
            if self.instance and self.instance.pk:
                return self.instance.attachment_file
            raise ValidationError(
                'Attachment file is required'
            )
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in _ALLOWED_EXT:
            raise ValidationError(
                'Allowed: PDF, JPG, PNG, DOC, DOCX'
            )
        if file.size > _MAX_ATTACHMENT_BYTES:
            raise ValidationError(
                f'Max 10MB. '
                f'Your file: '
                f'{round(file.size/1024/1024,1)}MB'
            )
        return file

    def clean_record_status(self):
        value = (self.cleaned_data.get('record_status') or '').strip()
        if not value:
            raise ValidationError('Please select a status.')
        valid = {c[0] for c in DriverAttachment.RecordStatus.choices}
        if value not in valid:
            raise ValidationError('Invalid status.')
        return value

    def clean(self):
        cleaned = super().clean()
        is_expiry = cleaned.get('is_expiry_applicable')
        expiry = cleaned.get('expiry_date')
        if is_expiry and not expiry:
            self.add_error(
                'expiry_date',
                'Expiry date required when applicable',
            )
        if not is_expiry:
            cleaned['expiry_date'] = None
        return cleaned


class DriverSettingsForm(forms.ModelForm):
    class Meta:
        model = DriverSettings
        fields = [
            'default_driver_status',
            'document_expiry_alert_days',
            'driver_assignment_required',
        ]
        widgets = {
            'default_driver_status': forms.Select(
                attrs={'class': 'form-select'}
            ),
            'document_expiry_alert_days': forms.NumberInput(
                attrs={
                    'class': 'form-control has-icon',
                    'min': 0,
                    'max': 180,
                }
            ),
            'driver_assignment_required': forms.CheckboxInput(),
        }

    def clean_document_expiry_alert_days(self):
        val = self.cleaned_data.get(
            'document_expiry_alert_days'
        )
        if val is not None and (val < 0 or val > 180):
            raise ValidationError(
                'Must be between 0 and 180'
            )
        return val
