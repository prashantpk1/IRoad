"""
mobile_api/execution/dto/execution_validation_error.py

Structured validation error contract for execute-action failures.
"""
from __future__ import annotations

from typing import Any, TypedDict


class ExecutionValidationErrorBody(TypedDict, total=False):
    """Machine-readable validation failure returned to mobile clients."""

    error_code: str
    message: str
    refresh_required: bool
    next_action_hint: dict[str, Any]
    field: str


def build_validation_error(
    *,
    error_code: str,
    message: str,
    refresh_required: bool = True,
    next_action_hint: dict[str, Any] | None = None,
    field: str = '',
    sync_metadata: dict[str, Any] | None = None,
) -> ExecutionValidationErrorBody:
    body: ExecutionValidationErrorBody = ExecutionValidationErrorBody(
        error_code=(error_code or 'execute_validation_failed').strip(),
        message=(message or 'Validation failed.').strip(),
        refresh_required=bool(refresh_required),
    )
    if next_action_hint:
        body['next_action_hint'] = dict(next_action_hint)
    field_name = (field or '').strip()
    if field_name:
        body['field'] = field_name
    if sync_metadata:
        body['sync_metadata'] = dict(sync_metadata)  # type: ignore[typeddict-unknown-key]
    return body


def validation_error_as_details(body: ExecutionValidationErrorBody) -> dict[str, Any]:
    """Map to DRF ``error()`` ``data`` / ``details`` envelope."""
    return dict(body)
