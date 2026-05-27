"""
mobile_api/pod_capture/exceptions.py

Domain errors for POD capture orchestration (view HTTP mapping).
"""
from __future__ import annotations

from typing import Any

from mobile_api.pod_capture.dto.validation_error import (
    PodCaptureValidationErrorBody,
    build_validation_error,
)


def pod_capture_error_from_resolver(
    *,
    error_code: str | None,
    error_message: str | None,
) -> PodCaptureError:
    """Map job_detail resolver ``error_code`` to POD capture HTTP errors."""
    code = (error_code or 'pod_capture_error').strip()
    msg = (error_message or 'POD capture request failed.').strip()

    if code == 'job_not_found':
        return PodCaptureError(
            msg,
            code='job_not_found',
            http_status=404,
            message_key='mobile.jobs.not_found',
            refresh_required=False,
        )
    if code == 'job_inactive':
        return PodCaptureError(
            msg,
            code='job_inactive',
            http_status=404,
            message_key='mobile.jobs.inactive',
            refresh_required=False,
        )
    if code == 'forbidden':
        return PodCaptureError(
            msg,
            code='forbidden',
            http_status=403,
            message_key='mobile.auth.forbidden',
            refresh_required=False,
        )
    if code in ('driver_inactive', 'unauthorized', 'driver_not_resolved'):
        return PodCaptureError(
            msg,
            code=code,
            http_status=401,
            message_key='mobile.auth.unauthorized',
            refresh_required=False,
        )
    if code == 'tenant_required':
        return PodCaptureError(
            msg,
            code='tenant_required',
            http_status=400,
            message_key='mobile.auth.tenant_required',
            refresh_required=False,
        )
    if code == 'invalid_job_reference':
        return PodCaptureError(
            msg,
            code='invalid_job_reference',
            http_status=400,
            message_key='mobile.validation.failed',
            refresh_required=False,
        )
    return PodCaptureError(
        msg,
        code=code,
        http_status=400,
        message_key='mobile.validation.failed',
        refresh_required=False,
    )


class PodCaptureError(Exception):
    """POD capture failure with HTTP mapping for the view layer."""

    def __init__(
        self,
        message: str,
        *,
        code: str = 'pod_capture_error',
        http_status: int = 400,
        message_key: str = 'mobile.validation.failed',
        refresh_required: bool = False,
        validation_error: PodCaptureValidationErrorBody | None = None,
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
        return dict(self.validation_error)
