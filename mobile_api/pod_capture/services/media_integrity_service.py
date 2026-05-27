"""
mobile_api/pod_capture/services/media_integrity_service.py

SHA256 integrity for staged POD media and bundle aggregates.
"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable

from django.utils.translation import gettext_lazy as _

from mobile_api.pod_capture.dto.staging_models import PODCaptureBundle, PODCaptureMedia
from mobile_api.pod_capture.exceptions import PodCaptureError


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checksum_for_media_row(row: PODCaptureMedia) -> str:
    """Deterministic checksum from media metadata (file bytes verified at storage layer)."""
    payload = '|'.join(
        [
            (row.file_ref or '').strip(),
            (row.media_type or '').strip(),
            (row.mime_type or '').strip(),
            str(row.line_no),
            (row.file_name or '').strip(),
        ]
    )
    return sha256_hex(payload.encode('utf-8'))


def aggregate_bundle_checksum(
    bundle: PODCaptureBundle,
    media_rows: Iterable[PODCaptureMedia],
) -> str:
    parts: list[str] = [
        bundle.bundle_id,
        bundle.client_capture_id,
        bundle.shipment_id,
        bundle.driver_id,
        bundle.tenant_schema,
        bundle.content_hash or '',
    ]
    for row in sorted(media_rows, key=lambda r: (r.line_no, r.media_id)):
        parts.append(row.checksum or checksum_for_media_row(row))
    return sha256_hex(json.dumps(parts, sort_keys=True).encode('utf-8'))


class MediaIntegrityService:
    """Compute and verify tamper-evident checksums."""

    def assign_media_checksums(self, rows: list[PODCaptureMedia]) -> list[PODCaptureMedia]:
        for row in rows:
            if not (row.checksum or '').strip():
                row.checksum = checksum_for_media_row(row)
        return rows

    def seal_bundle(
        self,
        bundle: PODCaptureBundle,
        media_rows: list[PODCaptureMedia],
    ) -> str:
        rows = self.assign_media_checksums(media_rows)
        digest = aggregate_bundle_checksum(bundle, rows)
        bundle.integrity_checksum = digest
        return digest

    def verify_bundle_integrity(
        self,
        bundle: PODCaptureBundle,
        media_rows: list[PODCaptureMedia],
    ) -> None:
        expected = (bundle.integrity_checksum or '').strip()
        if not expected:
            return
        actual = aggregate_bundle_checksum(bundle, media_rows)
        if actual != expected:
            raise PodCaptureError(
                str(_('mobile.pod_capture.integrity_checksum_mismatch')),
                code='integrity_checksum_mismatch',
                http_status=409,
                message_key='mobile.pod_capture.integrity_checksum_mismatch',
            )

    def verify_media_checksums(self, media_rows: list[PODCaptureMedia]) -> None:
        for row in media_rows:
            provided = (row.checksum or '').strip()
            if not provided:
                continue
            actual = checksum_for_media_row(row)
            if provided != actual:
                raise PodCaptureError(
                    str(_('mobile.pod_capture.media_checksum_mismatch')),
                    code='media_checksum_mismatch',
                    http_status=409,
                    message_key='mobile.pod_capture.media_checksum_mismatch',
                )
