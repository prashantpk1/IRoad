"""Shared validators for Arabic-only, English-only, and digits-only text fields."""

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

# Basic Latin letters and common separators used in English names.
ENGLISH_TEXT_RE = re.compile(r"^[A-Za-z\s\-'.]+$", re.UNICODE)

DIGITS_ONLY_RE = re.compile(r'^\d+$')

# Long-form / template fields — not restricted to name/label character sets.
_ENGLISH_TEXT_FIELD_EXCLUSIONS = frozenset({
    'body_en',
    'body_ar',
    'subject_en',
    'subject_ar',
    'content_en',
    'content_ar',
    'meta_description_en',
    'meta_description_ar',
    'message_body',
    'description',
    'description_en',
    'description_ar',
})

_ENGLISH_TEXT_FIELD_INCLUSIONS = frozenset({
    'price_list_name',
})


def is_arabic_text_field(field_name: str) -> bool:
    name = (field_name or '').lower()
    if name in {'content_ar'}:
        return False
    return 'arabic' in name or name.endswith('_ar')


def is_english_text_field(field_name: str) -> bool:
    name = (field_name or '').lower()
    if name in _ENGLISH_TEXT_FIELD_EXCLUSIONS:
        return False
    if name in _ENGLISH_TEXT_FIELD_INCLUSIONS:
        return True
    if 'english' in name:
        return True
    return name.endswith('_en')


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


def english_text_input_attrs(**extra) -> dict:
    """Default HTML attrs for English-only inputs."""
    attrs = {
        'class': 'form-control eal-english',
        'lang': 'en',
        'data-english-only': '1',
        'autocomplete': 'off',
    }
    if extra:
        existing_class = extra.pop('class', '')
        if existing_class:
            classes = f'{attrs["class"]} {existing_class}'.strip()
            attrs['class'] = classes
        attrs.update(extra)
    return attrs


def apply_english_field_widgets(form) -> None:
    """Ensure English model/form fields expose client-side English-only markers."""
    for field_name, field in form.fields.items():
        if not is_english_text_field(field_name):
            continue
        widget = field.widget
        existing_classes = widget.attrs.get('class', '')
        if 'eal-english' not in existing_classes:
            widget.attrs['class'] = f'{existing_classes} eal-english'.strip()
        widget.attrs.setdefault('lang', 'en')
        widget.attrs.setdefault('data-english-only', '1')
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
    return _validate_form_field(
        form_errors,
        field_name,
        value,
        validate_arabic_text,
        required=required,
        field_label=field_label,
    )


def validate_english_text(
    value,
    *,
    required: bool = False,
    field_label: str | None = None,
) -> str:
    """Return stripped value or raise ValidationError when non-English characters appear."""
    stripped = (value or '').strip()
    label = field_label or _('English text')

    if not stripped:
        if required:
            raise ValidationError(_('%(field)s is required.') % {'field': label})
        return ''

    if not ENGLISH_TEXT_RE.fullmatch(stripped):
        raise ValidationError(
            _('%(field)s must contain English characters only.')
            % {'field': label}
        )
    return stripped


def validate_english_form_field(
    form_errors: dict,
    field_name: str,
    value,
    *,
    required: bool = False,
    field_label: str | None = None,
) -> str:
    """Validate a view-level English-only field and record the first error message."""
    return _validate_form_field(
        form_errors,
        field_name,
        value,
        validate_english_text,
        required=required,
        field_label=field_label,
    )


def validate_digits_only_text(
    value,
    *,
    required: bool = False,
    field_label: str | None = None,
) -> str:
    """Return stripped value or raise ValidationError when non-digit characters appear."""
    stripped = (value or '').strip()
    label = field_label or _('This field')

    if not stripped:
        if required:
            raise ValidationError(_('%(field)s is required.') % {'field': label})
        return ''

    if not DIGITS_ONLY_RE.fullmatch(stripped):
        raise ValidationError(
            _('%(field)s must contain digits only.')
            % {'field': label}
        )
    return stripped


def validate_digits_only_form_field(
    form_errors: dict,
    field_name: str,
    value,
    *,
    required: bool = False,
    field_label: str | None = None,
) -> str:
    """Validate a view-level digits-only field and record the first error message."""
    return _validate_form_field(
        form_errors,
        field_name,
        value,
        validate_digits_only_text,
        required=required,
        field_label=field_label,
    )


DIGIT_CHAR_RE = re.compile(r'\d')


def validate_no_digits_text(
    value,
    *,
    required: bool = False,
    field_label: str | None = None,
) -> str:
    """Return stripped value or raise ValidationError when digits appear."""
    stripped = (value or '').strip()
    label = field_label or _('This field')

    if not stripped:
        if required:
            raise ValidationError(_('%(field)s is required.') % {'field': label})
        return ''

    if DIGIT_CHAR_RE.search(stripped):
        raise ValidationError(
            _('%(field)s must not contain numbers.')
            % {'field': label}
        )
    return stripped


def validate_no_digits_form_field(
    form_errors: dict,
    field_name: str,
    value,
    *,
    required: bool = False,
    field_label: str | None = None,
) -> str:
    """Validate a view-level no-digits field and record the first error message."""
    return _validate_form_field(
        form_errors,
        field_name,
        value,
        validate_no_digits_text,
        required=required,
        field_label=field_label,
    )


def _validate_form_field(
    form_errors: dict,
    field_name: str,
    value,
    validator,
    *,
    required: bool = False,
    field_label: str | None = None,
) -> str:
    try:
        return validator(value, required=required, field_label=field_label)
    except ValidationError as exc:
        messages = exc.messages
        form_errors[field_name] = messages[0] if messages else str(exc)
        return (value or '').strip()


def validate_name_label_field_formats(
    form_data: dict,
    form_errors: dict,
    specs: tuple[tuple[str, str, str, bool], ...],
) -> None:
    """
    Validate bilingual name/label fields in manual POST handlers.

    Each spec is ``(field_name, field_label, language, required)`` where
    ``language`` is ``'arabic'`` or ``'english'``.
    """
    for field_name, field_label, language, required in specs:
        if language == 'arabic':
            form_data[field_name] = validate_arabic_form_field(
                form_errors,
                field_name,
                form_data.get(field_name),
                required=required,
                field_label=field_label,
            )
        else:
            form_data[field_name] = validate_english_form_field(
                form_errors,
                field_name,
                form_data.get(field_name),
                required=required,
                field_label=field_label,
            )


class ArabicTextFormMixin:
    """Validate Arabic/English name and label fields on ModelForms."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_arabic_field_widgets(self)
        apply_english_field_widgets(self)

    def clean(self):
        cleaned_data = super().clean()
        for field_name, field in self.fields.items():
            if field_name not in cleaned_data:
                continue
            raw = cleaned_data.get(field_name)
            if raw is None:
                continue
            if is_arabic_text_field(field_name):
                try:
                    cleaned_data[field_name] = validate_arabic_text(
                        raw,
                        required=field.required,
                        field_label=field.label,
                    )
                except ValidationError as exc:
                    self.add_error(field_name, exc)
            elif is_english_text_field(field_name):
                try:
                    cleaned_data[field_name] = validate_english_text(
                        raw,
                        required=field.required,
                        field_label=field.label,
                    )
                except ValidationError as exc:
                    self.add_error(field_name, exc)
        return cleaned_data
