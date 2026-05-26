"""
mobile_api/execution/services/execution_response_service.py

Post-execute read model assembly (workflow, pod_cod, round_trip, sync_metadata).
"""
from __future__ import annotations

from typing import Any

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.dto.execute_action_response_builder import (
    ExecuteActionApiPayload,
    ExecuteActionResponseBuilder,
)
from mobile_api.execution.dto.execute_action_result import ExecuteActionResult
from mobile_api.execution.services.execution_reconcile_service import (
    ExecutionReconcileService,
)


class ExecutionResponseService:
    """Build the outward execute response after kernel + post-reconcile."""

    def __init__(
        self,
        *,
        response_builder: ExecuteActionResponseBuilder | None = None,
        reconcile_service: ExecutionReconcileService | None = None,
    ) -> None:
        self._response_builder = response_builder or ExecuteActionResponseBuilder()
        self._reconcile_service = reconcile_service or ExecutionReconcileService()

    def build_execute_result(
        self,
        context: ExecuteActionContext,
        *,
        request: Any | None = None,
    ) -> ExecuteActionResult:
        """Post-reconcile projections then map to API envelope."""
        self._reconcile_service.reconcile_post_execute(context, request=request)
        payload: ExecuteActionApiPayload = self._response_builder.build(context)
        http_status = 200 if context.reused_existing else 201
        return ExecuteActionResult(payload=dict(payload), http_status=http_status)
