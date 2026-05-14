"""
mobile_api/helpers/i18n.py

Language activation helper for Mobile API.

Mobile clients send language preference via:

  Accept-Language: ar, en;q=0.9

If missing or unsupported, defaults to English (``en``).

Supported languages: en, ar

Usage in a view:
    from mobile_api.helpers.i18n import activate_request_language
    from django.utils.translation import gettext as _

    activate_request_language(request)
    message = _('mobile.truck.list.success')
    return api_success(message, data=...)
"""
from __future__ import annotations

from typing import Any

from django.utils import translation


SUPPORTED_LANGUAGES = {'en', 'ar'}
DEFAULT_LANGUAGE = 'en'


def get_request_language(request) -> str:
    """
    Determine language from ``Accept-Language`` only.

    Priority:
      1. Accept-Language header (first tag, e.g. ``ar,en;q=0.9`` → ``ar``)
      2. Default: ``en``

    Returns:
        Language code string: ``en`` or ``ar``
    """
    accept_lang = (
        request.headers.get('Accept-Language', '').strip().lower()
        if request is not None
        else ''
    )
    if accept_lang:
        first = accept_lang.split(',')[0].strip()
        lang_code = first[:2]
        if lang_code in SUPPORTED_LANGUAGES:
            return lang_code

    return DEFAULT_LANGUAGE


def activate_request_language(request) -> str:
    """
    Detect language from request and activate Django translation.

    Call this at the start of every API view.
    Returns the activated language code.

    Example:
        lang = activate_request_language(request)
        # Now _('key') returns in the correct language
    """
    lang = get_request_language(request)
    translation.activate(lang)
    return lang


def deactivate_language():
    """
    Deactivate translation after request.
    Call in finally block if needed.
    """
    translation.deactivate()


def get_localized_value(
    request,
    english_value: Any,
    arabic_value: Any,
) -> str:
    """
    Pick a single display string for bilingual model fields.

    - When resolved language is ``ar``, prefers Arabic; falls back to English if empty.
    - Otherwise prefers English; falls back to Arabic if empty.

    ``request`` may be ``None`` (defaults to English selection behavior).
    """
    lang = get_request_language(request) if request is not None else DEFAULT_LANGUAGE
    en_s = '' if english_value is None else str(english_value)
    ar_s = '' if arabic_value is None else str(arabic_value)
    en_s = en_s.strip()
    ar_s = ar_s.strip()
    if lang == 'ar':
        return ar_s if ar_s else en_s
    return en_s if en_s else ar_s


def localized_pair_to_single(
    request,
    *,
    english_value: Any,
    arabic_value: Any,
    field_name: str = 'name',
) -> dict[str, str]:
    """
    Build a one-key dict for API responses (e.g. ``{"name": "..."}``).

    DB / model field names stay ``english_*`` / ``arabic_*``; only the JSON
    output shape uses ``field_name``.
    """
    return {
        field_name: get_localized_value(request, english_value, arabic_value),
    }
