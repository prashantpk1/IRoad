"""
mobile_api/pod_capture/dto/pod_capture_context.py

Request-scoped context for one POD capture orchestration pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from mobile_api.pod_capture.dto.staging_models import (
    PODCaptureBundle,
    PODCaptureMedia,
    PODCaptureMediaItemInput,
)


@dataclass
class PodCaptureContext:
    """
    Shipment-only POD capture boundary context.

    No ``operation_action``, ``action_log``, or workflow mutation fields — evidence only.
    """

    driver: Any
    tenant_schema: str
    shipment_id: str
    payload: Mapping[str, Any]
    request: Any | None = None
    user_id: str = ''

    shipment: Any | None = None
    booking: Any | None = None

    client_capture_id: str = ''
    content_hash: str = ''
    workflow_version: str = ''
    pod_capture_type: str = ''
    target_action_code: str = ''
    notes: str = ''
    latitude: str = ''
    longitude: str = ''

    operation_action: Any | None = None
    compliance_requirements: dict[str, Any] = field(default_factory=dict)

    media_items: list[PODCaptureMediaItemInput] = field(default_factory=list)

    bundle: PODCaptureBundle | None = None
    staged_media: list[PODCaptureMedia] = field(default_factory=list)

    sync_metadata: dict[str, Any] = field(default_factory=dict)
    idempotent_replay: bool = False
    resolver_meta: dict[str, Any] = field(default_factory=dict)
