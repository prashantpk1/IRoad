"""
mobile_api/execution/dto/execution_authoritative_context.py

Reconciled workflow authority shared by GET Job Detail and POST Execute.

Ensures kernel validation sees the same log-primary status as allowed-actions projection.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.services.execution_context_adapter import to_job_detail_context
from mobile_api.job_detail.services.job_detail_status_reconciler import (
    apply_reconciled_status_overlays,
    authoritative_entity_status,
    entity_reconciliation_block,
)


@dataclass(frozen=True)
class ExecutionAuthoritativeContext:
    """
    Immutable reconciled authority snapshot for one execute attempt.

    Built after ``prepare_pre_execute`` — must not trust ORM column status alone.
    """

    job_type: str
    authoritative_status: str
    allowed_action_codes: frozenset[str]
    sync_metadata: dict[str, Any] = field(default_factory=dict)
    reconciliation: dict[str, Any] = field(default_factory=dict)
    workflow: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_execute_context(cls, context: ExecuteActionContext) -> ExecutionAuthoritativeContext:
        auth = dict(context.authoritative or {})
        workflow = dict(context.workflow or auth.get('workflow') or {})
        allowed: set[str] = set()
        for item in list(auth.get('allowed_actions') or workflow.get('allowed_actions') or []):
            if isinstance(item, dict):
                code = str(item.get('action_code') or '').strip()
                if code:
                    allowed.add(code)

        job_detail_ctx = to_job_detail_context(context)
        status = authoritative_entity_status(job_detail_ctx)
        if not status:
            block = entity_reconciliation_block(job_detail_ctx)
            status = str(block.get('authoritative_status') or '').strip()

        return cls(
            job_type=context.job_type,
            authoritative_status=status,
            allowed_action_codes=frozenset(allowed),
            sync_metadata=dict(context.sync_metadata or auth.get('sync_metadata') or {}),
            reconciliation=dict(context.reconciliation or {}),
            workflow=workflow,
        )

    def action_code_allowed(self, action_code: str) -> bool:
        token = (action_code or '').strip()
        if not token:
            return False
        normalized = {c.casefold() for c in self.allowed_action_codes}
        return token.casefold() in normalized


@contextmanager
def kernel_validation_overlay(context: ExecuteActionContext) -> Iterator[None]:
    """
  Apply reconciled status overlays while the execution kernel validates / mutates.

  Mutates in-memory ORM instances only (no DB write) — matches Job Detail GET path.
    """
    job_detail_ctx = to_job_detail_context(context)
    with apply_reconciled_status_overlays(job_detail_ctx):
        yield
