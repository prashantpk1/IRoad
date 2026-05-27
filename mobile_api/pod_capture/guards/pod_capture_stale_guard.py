"""
mobile_api/pod_capture/guards/pod_capture_stale_guard.py

Reject capture when client Job Detail sync fingerprints are behind server state.

Mirrors execute stale guard semantics without invoking workflow execution.
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.validation_error import build_validation_error
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.settings import pod_capture_require_sync_metadata


class PodCaptureStaleGuard:
    """Compare client ``content_hash`` / ``workflow_version`` against server sync."""

    def assert_not_stale(self, context: PodCaptureContext) -> None:
        if context.idempotent_replay:
            return

        expectations = self.extract_client_sync_expectations(context)
        sync = dict(context.sync_metadata or {})

        if pod_capture_require_sync_metadata():
            self._assert_required_sync_fields(expectations)

        if not self._client_sent_stale_checks(expectations):
            return

        self._assert_content_hash(expectations, sync)
        self._assert_workflow_version(expectations, sync)

    def extract_client_sync_expectations(
        self,
        context: PodCaptureContext,
    ) -> dict[str, Any]:
        payload = dict(context.payload or {})
        entity_versions = payload.get('entity_versions')
        if not isinstance(entity_versions, dict):
            entity_versions = {}

        return {
            'expected_content_hash': str(
                payload.get('content_hash') or payload.get('expected_content_hash') or ''
            ).strip(),
            'expected_workflow_version': str(
                payload.get('workflow_version') or payload.get('expected_workflow_version') or ''
            ).strip(),
            'expected_entity_versions': {
                str(k): str(v or '').strip() for k, v in entity_versions.items()
            },
        }

    @staticmethod
    def _client_sent_stale_checks(expectations: dict[str, Any]) -> bool:
        return bool(
            expectations.get('expected_content_hash')
            or expectations.get('expected_workflow_version')
            or expectations.get('expected_entity_versions')
        )

    def _assert_required_sync_fields(self, expectations: dict[str, Any]) -> None:
        if not expectations.get('expected_content_hash'):
            raise self._stale_error(
                'sync_content_hash_required',
                str(_('mobile.pod_capture.sync_content_hash_required')),
            )
        if not expectations.get('expected_workflow_version'):
            raise self._stale_error(
                'sync_workflow_version_required',
                str(_('mobile.pod_capture.sync_workflow_version_required')),
            )

    @staticmethod
    def _assert_content_hash(expectations: dict[str, Any], sync: dict[str, Any]) -> None:
        expected = expectations.get('expected_content_hash') or ''
        server = str(sync.get('content_hash') or '').strip()
        if expected and server and expected != server:
            raise PodCaptureStaleGuard._stale_error(
                'stale_content_hash',
                str(_('mobile.pod_capture.stale_content_hash')),
            )

    @staticmethod
    def _assert_workflow_version(expectations: dict[str, Any], sync: dict[str, Any]) -> None:
        expected = expectations.get('expected_workflow_version') or ''
        server = str(sync.get('workflow_version') or '').strip()
        if expected and server and expected != server:
            raise PodCaptureStaleGuard._stale_error(
                'stale_workflow_version',
                str(_('mobile.pod_capture.stale_workflow_version')),
            )

    @staticmethod
    def _stale_error(error_code: str, message: str) -> PodCaptureError:
        body = build_validation_error(
            error_code=error_code,
            message=message,
            refresh_required=True,
        )
        return PodCaptureError(
            message,
            code=error_code,
            http_status=409,
            message_key=f'mobile.pod_capture.{error_code}',
            refresh_required=True,
            validation_error=body,
        )
