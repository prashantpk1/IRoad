"""
Thread-local guard for mobile driver action execution.

``ActionExecutionService.execute_driver_action`` with ``SOURCE_CHANNEL_MOBILE_DRIVER``
must run inside an active guard so internal/celery/management callers cannot bypass
driver-scoped authorization at the mobile boundary.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER


@dataclass(frozen=True)
class MobileExecutionContext:
    """Bound mobile principal for one driver action execution."""

    driver: Any
    tenant_user: Any
    tenant_schema: str
    driver_id: str
    user_id: str
    jwt_driver_id: str | None = None


_guard: contextvars.ContextVar[MobileExecutionContext | None] = contextvars.ContextVar(
    'mobile_execution_guard',
    default=None,
)


class MobileExecutionGuardError(ValidationError):
    """Raised when mobile execution runs without an active execution context."""


def get_active_mobile_execution_context() -> MobileExecutionContext | None:
    return _guard.get()


def _driver_pk(driver) -> Any:
    return getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)


def assert_mobile_execution_guard_allows(
    *,
    driver=None,
    shipment=None,
    movement=None,
    source_channel: str = SOURCE_CHANNEL_MOBILE_DRIVER,
) -> MobileExecutionContext:
    """Ensure mobile-channel execution was opened with ``mobile_execution_guard``."""
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
def mobile_execution_guard(ctx: MobileExecutionContext):
    """Activate guard for one mobile execute transaction (per-thread/async task)."""
    token = _guard.set(ctx)
    try:
        yield ctx
    finally:
        _guard.reset(token)


def mobile_execution_guard_is_active() -> bool:
    return _guard.get() is not None
