"""
mobile_api/execution/exceptions.py

Domain errors for mobile execute-action orchestration (view HTTP mapping).
"""
from __future__ import annotations

from typing import Any

from mobile_api.execution.dto.execution_validation_error import (
    ExecutionValidationErrorBody,
    build_validation_error,
)


def execute_action_error_from_resolver(
    *,
    error_code: str | None,
    error_message: str | None,
) -> ExecuteActionError:
    """Map job_detail resolver ``error_code`` to execute-action HTTP errors."""
    code = (error_code or 'execute_action_error').strip()
    msg = (error_message or 'Execute action request failed.').strip()

    if code == 'job_not_found':
        return ExecuteActionError(
            msg,
            code='job_not_found',
            http_status=404,
            message_key='mobile.jobs.not_found',
            refresh_required=False,
        )
    if code == 'job_inactive':
        return ExecuteActionError(
            msg,
            code='job_inactive',
            http_status=404,
            message_key='mobile.jobs.inactive',
            refresh_required=False,
        )
    if code == 'not_empty_move':
        return ExecuteActionError(
            msg,
            code='not_empty_move',
            http_status=400,
            message_key='mobile.jobs.not_empty_move',
            refresh_required=False,
        )
    if code == 'forbidden':
        return ExecuteActionError(
            msg,
            code='forbidden',
            http_status=403,
            message_key='mobile.auth.forbidden',
            refresh_required=False,
        )
    if code in ('driver_inactive', 'unauthorized', 'driver_not_resolved'):
        return ExecuteActionError(
            msg,
            code=code,
            http_status=401,
            message_key='mobile.auth.unauthorized',
            refresh_required=False,
        )
    if code == 'tenant_required':
        return ExecuteActionError(
            msg,
            code='tenant_required',
            http_status=400,
            message_key='mobile.auth.tenant_required',
            refresh_required=False,
        )
    if code == 'invalid_job_reference':
        return ExecuteActionError(
            msg,
            code='invalid_job_reference',
            http_status=400,
            message_key='mobile.validation.failed',
            refresh_required=False,
        )
    return ExecuteActionError(
        msg,
        code=code,
        http_status=400,
        message_key='mobile.validation.failed',
        refresh_required=False,
    )


class ExecuteActionError(Exception):
    """Execute-action failure with HTTP mapping for the view layer."""

    def __init__(
        self,
        message: str,
        *,
        code: str = 'execute_action_error',
        http_status: int = 400,
        message_key: str = 'mobile.validation.failed',
        refresh_required: bool = False,
        validation_error: ExecutionValidationErrorBody | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message_key = message_key
        self.refresh_required = refresh_required
        self.validation_error = validation_error or build_validation_error(
            error_code=code,
            message=message,
            refresh_required=refresh_required,
        )

    def to_validation_dict(self) -> dict[str, Any]:
        """Structured validation payload for API ``data``."""
        return dict(self.validation_error)
