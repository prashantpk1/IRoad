"""
mobile_api/pod_capture/settings.py

Tunable POD capture boundary flags (Django settings overrides).
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def pod_capture_require_sync_metadata() -> bool:
    """When True, capture requests must send ``content_hash`` + ``workflow_version``."""
    return bool(getattr(settings, 'MOBILE_POD_CAPTURE_REQUIRE_SYNC_METADATA', True))


def pod_capture_verify_media_storage() -> bool:
    """When True, ``file_ref`` must exist in default storage and pass path policy."""
    return pod_capture_require_storage_verification()


def pod_capture_bundle_ttl() -> timedelta:
    """Default expiry for staged bundles (durable ``expires_at`` on ORM)."""
    hours = int(
        getattr(
            settings,
            'MOBILE_POD_BUNDLE_TTL_HOURS',
            getattr(settings, 'MOBILE_POD_CAPTURE_BUNDLE_TTL_HOURS', 72),
        )
    )
    return timedelta(hours=max(1, hours))


def pod_capture_default_expires_at():
    return timezone.now() + pod_capture_bundle_ttl()


def pod_capture_require_storage_verification() -> bool:
    return bool(
        getattr(
            settings,
            'MOBILE_POD_CAPTURE_REQUIRE_STORAGE_VERIFICATION',
            getattr(settings, 'MOBILE_POD_CAPTURE_VERIFY_MEDIA_STORAGE', True),
        )
    )


def pod_capture_enforce_immutability() -> bool:
    return bool(getattr(settings, 'MOBILE_POD_CAPTURE_ENFORCE_IMMUTABILITY', True))
