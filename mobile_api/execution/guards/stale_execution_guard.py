"""
mobile_api/execution/guards/stale_execution_guard.py

Reject execute when client sync fingerprints are behind server pre-execute state.
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.dto.execution_validation_error import build_validation_error
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.settings import mobile_execution_require_sync_metadata


class StaleExecutionGuard:
    """
    Compare client-supplied sync fields against server ``sync_metadata``.

    Accepts canonical API fields ``content_hash`` / ``workflow_version`` (and legacy
    ``expected_*`` aliases). Rejects on mismatch (HTTP 409, ``refresh_required``).
    Skipped for idempotent replay retries.
    """

    def assert_not_stale(self, context: ExecuteActionContext) -> None:
        """
        Raises:
            ExecuteActionError: Stale workflow / entity versions (HTTP 409).
        """
        if context.idempotent_replay:
            return

        expectations = self.extract_client_sync_expectations(context)
        sync = self._server_sync(context)

        if mobile_execution_require_sync_metadata():
            self._assert_required_sync_fields(expectations)

        if not self._client_sent_stale_checks(expectations):
            return

        self._assert_content_hash(context, expectations, sync)
        self._assert_workflow_version(expectations, sync)
        self._assert_entity_versions(expectations, sync)

    def extract_client_sync_expectations(
        self,
        context: ExecuteActionContext,
    ) -> dict[str, Any]:
        """Read stale-check fields from ``context.payload``."""
        payload = context.payload or {}
        entity_versions = payload.get('entity_versions')
        if not isinstance(entity_versions, dict):
            entity_versions = payload.get('expected_entity_versions')
        if not isinstance(entity_versions, dict):
            entity_versions = {}

        content_hash = str(
            payload.get('content_hash') or payload.get('expected_content_hash') or ''
        ).strip()
        workflow_version = str(
            payload.get('workflow_version') or payload.get('expected_workflow_version') or ''
        ).strip()

        return {
            'expected_content_hash': content_hash,
            'expected_workflow_version': workflow_version,
            'expected_entity_versions': {
                str(k): str(v or '').strip()
                for k, v in entity_versions.items()
            },
        }

    @staticmethod
    def _server_sync(context: ExecuteActionContext) -> dict[str, Any]:
        auth = context.authoritative or {}
        return dict(context.sync_metadata or auth.get('sync_metadata') or {})

    def _assert_required_sync_fields(self, expectations: dict[str, Any]) -> None:
        """Enterprise mode — client must send sync fingerprints on every fresh execute."""
        missing: list[str] = []
        if not expectations.get('expected_content_hash'):
            missing.append('content_hash')
        if not expectations.get('expected_workflow_version'):
            missing.append('workflow_version')
        if missing:
            self._raise_stale(
                str(_('mobile.jobs.execute.stale_workflow'))
                + f' (missing: {", ".join(missing)})',
                error_code='stale_workflow',
            )

    @staticmethod
    def _client_sent_stale_checks(expectations: dict[str, Any]) -> bool:
        if expectations.get('expected_content_hash'):
            return True
        if expectations.get('expected_workflow_version'):
            return True
        if expectations.get('expected_entity_versions'):
            return True
        return False

    def _assert_content_hash(
        self,
        context: ExecuteActionContext,
        expectations: dict[str, Any],
        sync: dict[str, Any],
    ) -> None:
        expected_hash = expectations['expected_content_hash']
        if not expected_hash:
            return
        server_hash = str(sync.get('content_hash') or context.content_hash or '').strip()
        if server_hash and expected_hash != server_hash:
            self._raise_stale(
                str(_('mobile.jobs.execute.stale_content_hash')),
                error_code='stale_content_hash',
            )

    def _assert_workflow_version(
        self,
        expectations: dict[str, Any],
        sync: dict[str, Any],
    ) -> None:
        expected_version = expectations['expected_workflow_version']
        if not expected_version:
            return
        server_version = str(sync.get('workflow_version') or '').strip()
        if server_version and expected_version != server_version:
            self._raise_stale(
                str(_('mobile.jobs.execute.stale_workflow_version')),
                error_code='stale_workflow_version',
            )

    def _assert_entity_versions(
        self,
        expectations: dict[str, Any],
        sync: dict[str, Any],
    ) -> None:
        client_versions = expectations.get('expected_entity_versions') or {}
        if not client_versions:
            return
        server_versions = dict(sync.get('entity_versions') or {})
        mismatched: list[str] = []
        for key, expected in client_versions.items():
            if not expected:
                continue
            server_val = str(server_versions.get(key) or '').strip()
            if server_val and expected != server_val:
                mismatched.append(str(key))
        if mismatched:
            self._raise_stale(
                str(_('mobile.jobs.execute.stale_entity_version')),
                error_code='stale_entity_version',
                details_keys=mismatched,
            )

    @staticmethod
    def _raise_stale(
        message: str,
        *,
        error_code: str = 'stale_workflow',
        details_keys: list[str] | None = None,
    ) -> None:
        body = build_validation_error(
            error_code=error_code,
            message=message,
            refresh_required=True,
        )
        if details_keys:
            body = dict(body)
            body['mismatched_entity_keys'] = details_keys  # type: ignore[assignment]
        raise ExecuteActionError(
            message,
            code=error_code,
            http_status=409,
            message_key='mobile.jobs.execute.stale_workflow',
            refresh_required=True,
            validation_error=body,
        )
