"""Shared validators for Arabic-only text fields."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Arabic script blocks, presentation forms, and common separators used in names.
ARABIC_TEXT_RE = re.compile(
    r'^[\s'
    r'\u0600-\u06FF'
    r'\u0750-\u077F'
    r'\u08A0-\u08FF'
    r'\uFB50-\uFDFF'
    r'\uFE70-\uFEFF'
    r']*$',
    re.UNICODE,
)


def is_arabic_text_field(field_name: str) -> bool:
    name = (field_name or '').lower()
    if name in {'content_ar'}:
        return False
    return 'arabic' in name or name.endswith('_ar')


def arabic_text_input_attrs(**extra) -> dict:
    """Default HTML attrs for Arabic-only inputs."""
    attrs = {
        'class': 'form-control eal-arabic',
        'dir': 'rtl',
        'lang': 'ar',
        'data-arabic-only': '1',
        'autocomplete': 'off',
    }
    if extra:
        existing_class = extra.pop('class', '')
        if existing_class:
            classes = f'{attrs["class"]} {existing_class}'.strip()
            attrs['class'] = classes
        attrs.update(extra)
    return attrs


def apply_arabic_field_widgets(form) -> None:
    """Ensure Arabic model/form fields expose client-side Arabic-only markers."""
    for field_name, field in form.fields.items():
        if not is_arabic_text_field(field_name):
            continue
        widget = field.widget
        existing_classes = widget.attrs.get('class', '')
        if 'eal-arabic' not in existing_classes:
            widget.attrs['class'] = f'{existing_classes} eal-arabic'.strip()
        widget.attrs.setdefault('dir', 'rtl')
        widget.attrs.setdefault('lang', 'ar')
        widget.attrs.setdefault('data-arabic-only', '1')
        widget.attrs.setdefault('autocomplete', 'off')


def validate_arabic_text(
    value,
    *,
    required: bool = False,
    field_label: str | None = None,
) -> str:
    """Return stripped value or raise ValidationError when non-Arabic characters appear."""
    stripped = (value or '').strip()
    label = field_label or _('Arabic text')

    if not stripped:
        if required:
            raise ValidationError(_('%(field)s is required.') % {'field': label})
        return ''

    if not ARABIC_TEXT_RE.fullmatch(stripped):
        raise ValidationError(
            _('%(field)s must contain Arabic characters only.')
            % {'field': label}
        )
    return stripped


def validate_arabic_form_field(
    form_errors: dict,
    field_name: str,
    value,
    *,
    required: bool = False,
    field_label: str | None = None,
) -> str:
    """Validate a view-level form field and record the first error message."""
    try:
        return validate_arabic_text(
            value,
            required=required,
            field_label=field_label,
        )
    except ValidationError as exc:
        messages = exc.messages
        form_errors[field_name] = messages[0] if messages else str(exc)
        return (value or '').strip()


class ArabicTextFormMixin:
    """Reject Latin digits/symbols in Arabic-labelled ModelForm fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_arabic_field_widgets(self)

    def clean(self):
        cleaned_data = super().clean()
        for field_name, field in self.fields.items():
            if not is_arabic_text_field(field_name):
                continue
            if field_name not in cleaned_data:
                continue
            raw = cleaned_data.get(field_name)
            if raw is None:
                continue
            try:
                cleaned_data[field_name] = validate_arabic_text(
                    raw,
                    required=field.required,
                    field_label=field.label,
                )
            except ValidationError as exc:
                self.add_error(field_name, exc)
        return cleaned_data
