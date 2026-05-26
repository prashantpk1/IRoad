"""
mobile_api/execution/dto/execution_validation_error.py

Structured validation error contract for execute-action failures.
"""
from __future__ import annotations

from typing import Any, TypedDict


class ExecutionValidationErrorBody(TypedDict):
    """Machine-readable validation failure returned to mobile clients."""

    error_code: str
    message: str
    refresh_required: bool


def build_validation_error(
    *,
    error_code: str,
    message: str,
    refresh_required: bool = True,
) -> ExecutionValidationErrorBody:
    return ExecutionValidationErrorBody(
        error_code=(error_code or 'execute_validation_failed').strip(),
        message=(message or 'Validation failed.').strip(),
        refresh_required=bool(refresh_required),
    )


def validation_error_as_details(body: ExecutionValidationErrorBody) -> dict[str, Any]:
    """Map to DRF ``error()`` ``data`` / ``details`` envelope."""
    return dict(body)
