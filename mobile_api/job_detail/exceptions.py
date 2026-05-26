"""
mobile_api/job_detail/exceptions.py

Domain errors for explicit job resolution and orchestration.
"""
from __future__ import annotations


class JobDetailError(Exception):
    """Resolvable job detail failure with HTTP mapping for the view layer."""

    def __init__(
        self,
        message: str,
        *,
        code: str = 'job_detail_error',
        http_status: int = 400,
        message_key: str = 'mobile.validation.failed',
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message_key = message_key


def job_detail_error_from_resolver(
    *,
    error_code: str | None,
    error_message: str | None,
) -> JobDetailError:
    """Map resolver ``error_code`` to HTTP status and API error code."""
    code = (error_code or 'job_detail_error').strip()
    msg = (error_message or 'Job detail request failed.').strip()

    if code == 'job_not_found':
        return JobDetailError(
            msg,
            code='job_not_found',
            http_status=404,
            message_key='mobile.jobs.not_found',
        )
    if code == 'job_inactive':
        return JobDetailError(
            msg,
            code='job_inactive',
            http_status=404,
            message_key='mobile.jobs.inactive',
        )
    if code == 'forbidden':
        return JobDetailError(
            msg,
            code='forbidden',
            http_status=403,
            message_key='mobile.auth.forbidden',
        )
    if code in ('driver_inactive', 'unauthorized'):
        return JobDetailError(
            msg,
            code=code,
            http_status=401,
            message_key='mobile.auth.unauthorized',
        )
    if code == 'tenant_required':
        return JobDetailError(
            msg,
            code='tenant_required',
            http_status=400,
            message_key='mobile.auth.tenant_required',
        )
    if code == 'invalid_job_reference':
        return JobDetailError(
            msg,
            code='invalid_job_reference',
            http_status=400,
            message_key='mobile.validation.failed',
        )
    return JobDetailError(
        msg,
        code=code,
        http_status=400,
        message_key='mobile.validation.failed',
    )
