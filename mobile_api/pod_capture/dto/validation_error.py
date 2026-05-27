"""
mobile_api/pod_capture/dto/validation_error.py

Structured validation error contract for POD capture failures.
"""
from __future__ import annotations

from typing import TypedDict


class PodCaptureValidationErrorBody(TypedDict):
    error_code: str
    message: str
    refresh_required: bool


def build_validation_error(
    *,
    error_code: str,
    message: str,
    refresh_required: bool = False,
) -> PodCaptureValidationErrorBody:
    return PodCaptureValidationErrorBody(
        error_code=(error_code or 'pod_capture_validation_failed').strip(),
        message=(message or 'Validation failed.').strip(),
        refresh_required=bool(refresh_required),
    )
