import os

from django import forms
from django.core.exceptions import ValidationError

from config.text_validators import ArabicTextFormMixin
from tenant_workspace.models import TruckAttachment


_ALLOWED_EXT = frozenset({'.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx'})
_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class TruckAttachmentForm(ArabicTextFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # On edit, keep current file when no replacement is uploaded.
        if self.instance and self.instance.pk and self.instance.attachment_file:
            self.fields['attachment_file'].required = False
            self.fields['attachment_file'].help_text = (
                'Leave empty to keep the current file. '
                'Upload to replace it.'
            )

        rs = self.fields['record_status']
        rs.choices = [
            ('', '-Select status-'),
        ] + list(TruckAttachment.RecordStatus.choices)
        rs.required = True
        rs.widget.attrs.setdefault('class', 'form-select')
        rs.help_text = 'Current status of the attachment'

    class Meta:
        model = TruckAttachment
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
                },
            ),
            'english_label': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter English label',
                },
            ),
            'doc_ref_number': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter document reference number',
                },
            ),
            'attachment_date': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control has-icon'},
            ),
            'is_expiry_applicable': forms.CheckboxInput(),
            'expiry_date': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control has-icon'},
            ),
            'record_status': forms.Select(
                attrs={'class': 'form-select'},
            ),
            'attachment_file': forms.FileInput(attrs={'class': 'form-control'}),
            'file_notes': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': (
                        'Describe this document (e.g. Insurance certificate valid until...)'
                    ),
                    'required': True,
                },
            ),
        }

    def clean_record_status(self):
        value = (self.cleaned_data.get('record_status') or '').strip()
        if not value:
            raise ValidationError('Please select a status.')
        valid = {c[0] for c in TruckAttachment.RecordStatus.choices}
        if value not in valid:
            raise ValidationError('Invalid status.')
        return value

    def clean_file_notes(self):
        notes = (self.cleaned_data.get('file_notes') or '').strip()
        if not notes:
            raise ValidationError('File notes are required')
        return notes

    def clean_attachment_file(self):
        file = self.cleaned_data.get('attachment_file')
        if not file:
            if self.instance and self.instance.pk:
                return self.instance.attachment_file
            raise ValidationError('Attachment file is required.')

        ext = os.path.splitext(file.name)[1].lower()
        if ext not in _ALLOWED_EXT:
            raise ValidationError(f'Allowed types: {", ".join(sorted(_ALLOWED_EXT))}')

        if file.size > _MAX_ATTACHMENT_BYTES:
            size_mb = round(file.size / 1024 / 1024, 1)
            raise ValidationError(
                f'File too large. Maximum size is 10MB. Your file is {size_mb}MB.'
            )

        return file

    def clean(self):
        cleaned = super().clean()
        applicable = bool(cleaned.get('is_expiry_applicable'))

        if not applicable:
            cleaned['expiry_date'] = None
        else:
            if not cleaned.get('expiry_date'):
                raise ValidationError(
                    {'expiry_date': 'Expiry date is required'},
                )

        return cleaned
