"""User-facing execute-action messages with gettext + English fallbacks."""
from __future__ import annotations

from django.utils.translation import gettext as _

_EXECUTE_MESSAGE_FALLBACKS: dict[str, str] = {
    'mobile.jobs.execute.notes_required': 'Notes are required for this action.',
    'mobile.jobs.execute.gps_required': 'GPS location is required for this action.',
    'mobile.jobs.execute.photo_required': 'At least one photo is required for this action.',
    'mobile.jobs.execute.signature_required': 'A signature is required for this action.',
    'mobile.jobs.execute.media_file_required': 'A media file is required for this action.',
}


def execute_user_message(message_key: str) -> str:
    """Return localized execute message; fall back to English when .po is missing."""
    key = (message_key or '').strip()
    if not key:
        return ''
    text = str(_(key))
    if text != key:
        return text
    return _EXECUTE_MESSAGE_FALLBACKS.get(key, text)


def execute_field_for_error_code(error_code: str) -> str:
    """Map execute validation codes to request payload fields for mobile forms."""
    mapping = {
        'notes_required': 'notes',
        'gps_required': 'latitude',
        'photo_required': 'media',
        'signature_required': 'media',
        'media_file_required': 'media',
        'video_required': 'media',
    }
    return mapping.get((error_code or '').strip(), '')
