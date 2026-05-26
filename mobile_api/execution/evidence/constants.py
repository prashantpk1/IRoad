"""
mobile_api/execution/evidence/constants.py

Server-side evidence limits (aligned with portal attachment UX).
"""
from __future__ import annotations

# Portal ``Operation-action-log`` media types (+ mobile signature capture).
ALLOWED_MEDIA_TYPES = frozenset({'photo', 'video', 'document', 'signature'})

PHOTO_MEDIA_TYPES = frozenset({'photo', 'signature'})
VIDEO_MEDIA_TYPES = frozenset({'video'})

EXECUTION_MEDIA_MAX_ITEMS = 20
EXECUTION_MEDIA_MAX_PHOTOS = 10
EXECUTION_MEDIA_MAX_VIDEOS = 3
EXECUTION_MEDIA_MAX_DOCUMENTS = 5

FILE_REF_MAX_LENGTH = 500
MEDIA_DESCRIPTION_MAX_LENGTH = 255
MEDIA_TYPE_MAX_LENGTH = 16
