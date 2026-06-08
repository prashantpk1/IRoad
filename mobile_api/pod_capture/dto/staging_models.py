"""
mobile_api/pod_capture/dto/staging_models.py

Staging contract for POD evidence (ORM migrations planned; dataclasses for foundation).

Bundle state machine::

    draft → ready → promoted
                 ↘ expired
                 ↘ rejected

Promotion means Execute Action consumed the bundle and Action Log linkage completed.

Each staged media row binds to: ``shipment_id``, ``driver_id``, ``tenant_schema``,
``client_capture_id`` (plus ``bundle_id``).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# Legal transitions (from_status -> {to_status, ...})
BUNDLE_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    'draft': frozenset({'ready', 'rejected', 'expired'}),
    'ready': frozenset({'promoted', 'expired', 'rejected'}),
    'promoted': frozenset(),
    'expired': frozenset(),
    'rejected': frozenset(),
}


class PODCaptureBundleStatus(str, Enum):
    """Shipment-scoped POD evidence bundle lifecycle."""

    DRAFT = 'draft'
    READY = 'ready'
    PROMOTED = 'promoted'
    EXPIRED = 'expired'
    REJECTED = 'rejected'

    @classmethod
    def terminal(cls) -> frozenset[str]:
        return frozenset({cls.PROMOTED.value, cls.EXPIRED.value, cls.REJECTED.value})


@dataclass
class PODCaptureBundle:
    """Bundle header — one offline capture session per ``client_capture_id`` + driver + tenant."""

    bundle_id: str
    client_capture_id: str
    shipment_id: str
    driver_id: str
    tenant_schema: str
    status: PODCaptureBundleStatus
    content_hash: str
    media_count: int = 0
    expires_at: datetime | None = None
    promoted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    promotion_action_log_id: str | None = None
    rejected_reason: str = ''
    workflow_version: str = ''
    pod_type: str = ''
    notes: str = ''
    latitude: str = ''
    longitude: str = ''
    integrity_checksum: str = ''
    capture_device_id: str = ''
    capture_app_version: str = ''
    replayed_from_bundle_id: str | None = None

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    def is_terminal(self) -> bool:
        return self.status.value in PODCaptureBundleStatus.terminal()

    def is_promoted(self) -> bool:
        return self.status == PODCaptureBundleStatus.PROMOTED or self.promoted_at is not None

    def is_promotable(self) -> bool:
        return (
            self.status == PODCaptureBundleStatus.READY
            and not self.is_promoted()
            and not self.is_expired()
        )

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if self.status == PODCaptureBundleStatus.EXPIRED:
            return True
        if self.expires_at is None:
            return False
        from django.utils import timezone

        current = now or timezone.now()
        return current >= self.expires_at

    def assert_transition(self, new_status: PODCaptureBundleStatus) -> None:
        allowed = BUNDLE_STATUS_TRANSITIONS.get(self.status.value, frozenset())
        if new_status.value not in allowed:
            raise ValueError(
                f'Invalid bundle transition {self.status.value} -> {new_status.value}'
            )


@dataclass
class PODCaptureMedia:
    """One staged file under a bundle — always shipment/driver/tenant scoped."""

    media_id: str
    bundle_id: str
    shipment_id: str
    driver_id: str
    tenant_schema: str
    client_capture_id: str
    media_type: str
    file_ref: str
    mime_type: str = ''
    uploaded_at: datetime | None = None
    checksum: str = ''
    line_no: int = 1
    file_name: str = ''
    description: str = ''
    captured_at: datetime | None = None
    promoted: bool = False
    immutable: bool = False
    promoted_at: datetime | None = None
    promoted_action_log_id: str | None = None
    mime_type: str = ''

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())


@dataclass
class PODCaptureMediaItemInput:
    """Normalized client media row before persistence to staging store."""

    media_type: str = ''
    file_ref: str = ''
    file_name: str = ''
    description: str = ''
    captured_at: datetime | None = None
    checksum: str = ''
    line_no: int = 0
    duration_seconds: float | None = None
    upload: Any | None = field(default=None, repr=False)


@dataclass(frozen=True)
class StagingScope:
    """Canonical ownership scope for one capture session."""

    tenant_schema: str
    driver_id: str
    shipment_id: str
    client_capture_id: str

    def storage_prefix(self) -> str:
        tenant = (self.tenant_schema or '').strip()
        driver = (self.driver_id or '').strip()
        shipment = (self.shipment_id or '').strip()
        return f'mobile_driver_uploads/{tenant}/{driver}/{shipment}/pod_capture/'
