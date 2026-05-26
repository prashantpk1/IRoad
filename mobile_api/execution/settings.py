"""
mobile_api/execution/settings.py

Tunable execution-boundary flags (Django settings overrides).
"""
from __future__ import annotations

from django.conf import settings


def mobile_execution_require_sync_metadata() -> bool:
    """When True, non-replay executes must send ``content_hash`` + ``workflow_version``."""
    return bool(getattr(settings, 'MOBILE_EXECUTION_REQUIRE_SYNC_METADATA', True))


def mobile_execution_verify_media_storage() -> bool:
    """When True, ``file_ref`` must exist in default storage and pass path policy."""
    return bool(getattr(settings, 'MOBILE_EXECUTION_VERIFY_MEDIA_STORAGE', True))


def mobile_execution_entity_locking_enabled() -> bool:
    """When True, ``select_for_update`` locks job rows for the execute transaction."""
    return bool(getattr(settings, 'MOBILE_EXECUTION_ENTITY_LOCKING_ENABLED', True))
