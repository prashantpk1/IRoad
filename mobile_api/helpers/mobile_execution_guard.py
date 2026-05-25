"""
Thread-local guard for mobile driver action execution.

``ActionExecutionService.execute_driver_action`` with ``SOURCE_CHANNEL_MOBILE_DRIVER``
must run inside an active guard so internal/celery/management callers cannot bypass
ownership + allowed-actions checks performed in ``DriverJobExecuteService``.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER

if TYPE_CHECKING:
    from mobile_api.helpers.job_execution_security import SecureJobExecutionContext

_guard: contextvars.ContextVar[SecureJobExecutionContext | None] = contextvars.ContextVar(
    'mobile_execution_guard',
    default=None,
)


class MobileExecutionGuardError(ValidationError):
    """Raised when mobile execution runs without a secure execution context."""


def get_active_mobile_execution_context() -> SecureJobExecutionContext | None:
    return _guard.get()


def _driver_pk(driver) -> Any:
    return getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)


def assert_mobile_execution_guard_allows(
    *,
    driver=None,
    shipment=None,
    movement=None,
    source_channel: str = SOURCE_CHANNEL_MOBILE_DRIVER,
) -> SecureJobExecutionContext:
    """
    Ensure mobile-channel execution was authorized through the Job Detail pipeline.
    """
    channel = (source_channel or '').strip()
    if channel != SOURCE_CHANNEL_MOBILE_DRIVER:
        return get_active_mobile_execution_context()  # type: ignore[return-value]

    ctx = _guard.get()
    if ctx is None:
        raise MobileExecutionGuardError(
            _('mobile.jobs.execute.execution_context_required'),
            code='execution_context_required',
        )

    if driver is not None:
        ctx_driver = _driver_pk(ctx.driver)
        call_driver = _driver_pk(driver)
        if ctx_driver is not None and call_driver is not None and ctx_driver != call_driver:
            raise MobileExecutionGuardError(
                _('mobile.jobs.execute.execution_context_driver_mismatch'),
                code='execution_context_driver_mismatch',
            )

    if shipment is not None and movement is not None:
        pass
    return ctx


@contextmanager
def mobile_execution_guard(ctx: SecureJobExecutionContext):
    """Activate guard for one mobile execute transaction (per-thread/async task)."""
    token = _guard.set(ctx)
    try:
        yield ctx
    finally:
        _guard.reset(token)


def mobile_execution_guard_is_active() -> bool:
    return _guard.get() is not None
