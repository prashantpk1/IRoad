"""
mobile_api/execution/guards/execution_idempotency_guard.py

Client idempotency key normalization and replay-safe duplicate detection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from django.utils.translation import gettext_lazy as _

from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
from iroad_tenants.operation_runtime.idempotency import (
    normalize_idempotency_key,
    normalize_source_ref,
)
from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.dto.execution_validation_error import build_validation_error
from mobile_api.execution.exceptions import ExecuteActionError


@dataclass(frozen=True)
class IdempotencyKeys:
    """Normalized keys passed to the execution kernel."""

    idempotency_key: str
    source_ref: str
    source_channel: str = SOURCE_CHANNEL_MOBILE_DRIVER


IdempotentLogLookup = Callable[[IdempotencyKeys], Any | None]


class ExecutionIdempotencyGuard:
    """
    Mobile execute requires ``client_action_id`` mapped to Action Log ``idempotency_key``.

    Replay-safe: an existing log for the same key is attached to context (kernel reuses).
    """

    def __init__(
        self,
        *,
        log_lookup: IdempotentLogLookup | None = None,
    ) -> None:
        self._log_lookup = log_lookup or self._default_log_lookup

    def assert_idempotency_key_present(self, context: ExecuteActionContext) -> None:
        """Reject when ``client_action_id`` / ``idempotency_key`` is missing."""
        keys = self._extract_raw_keys(context)
        if not keys['client_action_id'] and not keys['idempotency_key']:
            raise self._validation_error(
                error_code='idempotency_key_required',
                message=str(_('mobile.jobs.execute.idempotency_key_required')),
                refresh_required=False,
                http_status=400,
            )

    def normalize_request_keys(self, context: ExecuteActionContext) -> IdempotencyKeys:
        """
        Map ``client_action_id`` → ``idempotency_key`` (client_action_id wins).

        Persists normalized values on ``context``.
        """
        self.assert_idempotency_key_present(context)
        raw = self._extract_raw_keys(context)
        token = raw['client_action_id'] or raw['idempotency_key']
        idempotency_key = normalize_idempotency_key(token)
        if not idempotency_key:
            raise self._validation_error(
                error_code='idempotency_key_required',
                message=str(_('mobile.jobs.execute.idempotency_key_required')),
                refresh_required=False,
                http_status=400,
            )

        source_ref = normalize_source_ref(
            raw['source_ref']
            or self._default_source_ref(context),
        )
        keys = IdempotencyKeys(
            idempotency_key=idempotency_key,
            source_ref=source_ref,
        )
        context.idempotency_key = keys.idempotency_key
        context.source_ref = keys.source_ref
        return keys

    def detect_idempotent_replay(
        self,
        context: ExecuteActionContext,
        keys: IdempotencyKeys | None = None,
    ) -> bool:
        """
        When an Action Log already exists for the idempotency key, attach it for replay.

        Returns True when this request is a safe retry (no new validation of workflow).
        """
        normalized = keys or self.normalize_request_keys(context)
        existing = self._log_lookup(normalized)
        if existing is None:
            context.idempotent_replay = False
            return False

        if not self._idempotent_log_applies_to_context(context, existing):
            context.idempotent_replay = False
            return False

        context.action_log = existing
        context.reused_existing = True
        context.idempotent_replay = True

        existing_action = getattr(existing, 'operation_action', None)
        if existing_action is not None:
            context.operation_action = existing_action
            existing_code = str(getattr(existing_action, 'action_code', '') or '').strip()
            requested = (context.action_code or '').strip()
            if existing_code and requested and existing_code.casefold() != requested.casefold():
                raise self._validation_error(
                    error_code='action_master_mismatch',
                    message=str(_('mobile.jobs.execute.action_master_mismatch')),
                    refresh_required=True,
                    http_status=409,
                )
        return True

    @staticmethod
    def _extract_raw_keys(context: ExecuteActionContext) -> dict[str, str]:
        payload = context.payload or {}
        return {
            'client_action_id': str(payload.get('client_action_id') or '').strip(),
            'idempotency_key': str(payload.get('idempotency_key') or '').strip(),
            'source_ref': str(payload.get('source_ref') or '').strip(),
        }

    @staticmethod
    def _default_source_ref(context: ExecuteActionContext) -> str:
        action = (context.action_code or '').strip()
        job = (context.job_id or '').strip()
        if not action or not job:
            return ''
        leg = ''
        if context.job_type == 'booking' and context.booking is not None:
            from mobile_api.execution.services.execution_validation_service import (
                ExecutionValidationService,
            )

            leg = ExecutionValidationService._booking_item_type(context)
        elif context.shipment is not None:
            leg = str(getattr(context.shipment, 'booking_item_type', '') or '').strip()
        parts = [str(context.job_type or '').strip(), job]
        if leg:
            parts.append(leg)
        parts.append(action)
        return ':'.join(p for p in parts if p)[:128]

    def _idempotent_log_applies_to_context(
        self,
        context: ExecuteActionContext,
        log: Any,
    ) -> bool:
        """
        Outbound preshipment logs must not replay as backload executes (same A1 key).
        """
        if context.job_type != 'booking' or context.booking is None:
            return True
        from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
            booking_preshipment_log_in_cycle,
            is_backload_leg_pending,
            is_backload_preshipment_cycle,
        )
        from mobile_api.execution.services.execution_validation_service import (
            ExecutionValidationService,
        )

        booking = context.booking
        item_type = ExecutionValidationService._booking_item_type(context)
        if is_backload_preshipment_cycle(booking, item_type):
            return booking_preshipment_log_in_cycle(
                booking,
                log,
                booking_item_type=item_type,
            )
        if is_backload_leg_pending(booking):
            return booking_preshipment_log_in_cycle(
                booking,
                log,
                booking_item_type='Backload',
            )
        return True

    @staticmethod
    def _default_log_lookup(keys: IdempotencyKeys) -> Any | None:
        from iroad_tenants.services.action_execution_service import ActionExecutionService

        return ActionExecutionService._find_idempotent_existing(
            idempotency_key=keys.idempotency_key,
            source_channel=keys.source_channel,
            source_ref=keys.source_ref,
        )

    @staticmethod
    def _validation_error(
        *,
        error_code: str,
        message: str,
        refresh_required: bool,
        http_status: int,
    ) -> ExecuteActionError:
        body = build_validation_error(
            error_code=error_code,
            message=message,
            refresh_required=refresh_required,
        )
        return ExecuteActionError(
            message,
            code=error_code,
            http_status=http_status,
            message_key=f'mobile.jobs.execute.{error_code}',
            refresh_required=refresh_required,
            validation_error=body,
        )
