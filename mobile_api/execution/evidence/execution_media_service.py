"""
mobile_api/execution/evidence/execution_media_service.py

Persist ``TenantOperationActionMedia`` rows after kernel Action Log insert.

Uses shared ``persist_action_log_media_rows`` (portal-equivalent semantics).
"""
from __future__ import annotations

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.evidence.action_log_media_persistence import (
    ActionLogMediaItem,
    normalize_media_items,
    persist_action_log_media_rows,
)


class ExecutionMediaService:
    """
    Append-only media linkage to the created Action Log.

    Must run inside the orchestrator outer ``transaction.atomic`` after the kernel
    returns — any failure here rolls back the Action Log and side effects too.
    """

    def persist_execution_media(self, context: ExecuteActionContext) -> list:
        """
        Attach media rows to ``context.action_log``.

        Skips when:
          - idempotent replay (media already persisted on original execute)
          - no ``action_log`` on context
          - empty ``media`` payload
        """
        if context.idempotent_replay:
            return []
        action_log = context.action_log
        if action_log is None:
            return []

        items = normalize_media_items(list((context.payload or {}).get('media') or []))
        if not items:
            return []

        created_ids = persist_action_log_media_rows(
            action_log,
            items,
            replace_existing=not context.reused_existing,
        )
        context.resolver_meta = dict(context.resolver_meta or {})
        context.resolver_meta['media_row_ids'] = [str(pk) for pk in created_ids]
        return created_ids

    @staticmethod
    def build_media_items(context: ExecuteActionContext) -> list[ActionLogMediaItem]:
        """Expose normalized items for tests / orchestration."""
        return normalize_media_items(list((context.payload or {}).get('media') or []))
