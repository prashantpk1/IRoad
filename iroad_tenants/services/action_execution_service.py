"""
Transactional operation action log creation and side-effect application.

Used by portal Action Log create/edit and future mobile execute-action APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from iroad_tenants.operation_runtime.constants import (
    OPERATION_ACTION_LOG_AUTO_FORM_CODE,
    OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
    OPERATION_ACTION_LOG_REF_PREFIX,
    SOURCE_CHANNEL_ADMIN_MANUAL,
    SOURCE_CHANNEL_MOBILE_DRIVER,
)
from iroad_tenants.operation_runtime.idempotency import (
    find_recent_duplicate,
    normalize_idempotency_key,
    normalize_source_ref,
)
from iroad_tenants.operation_runtime.latest_state import sync_shipment_status_from_action_log
from iroad_tenants.services.operation_execution_service import OperationExecutionService
from tenant_workspace.models import TenantOperationActionLog, TenantShipment


@dataclass(frozen=True)
class ActionExecutionResult:
    action_log: TenantOperationActionLog
    reused_existing: bool = False


class ActionExecutionService:
    """Create action logs and apply impacts atomically."""

    @staticmethod
    def validate_driver_action_execution(
        operation_action,
        *,
        booking=None,
        shipment=None,
        movement=None,
        booking_item_type: str = '',
        exclude_log_id=None,
        previous_action_id=None,
    ) -> str | None:
        return OperationExecutionService.validate_driver_action_execution(
            operation_action,
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
            exclude_log_id=exclude_log_id,
            previous_action_id=previous_action_id,
        )

    @staticmethod
    def apply_execution_side_effects(action_log, *, created_by_label=''):
        from iroad_tenants.operation_runtime.side_effects import (
            apply_execution_side_effects as _apply,
        )

        return _apply(action_log, created_by_label=created_by_label)

    @staticmethod
    def _allocate_log_no() -> tuple[str, int]:
        from iroad_tenants.views import _next_auto_number_for_form

        for _ in range(10):
            log_no, log_sequence = _next_auto_number_for_form(
                form_code=OPERATION_ACTION_LOG_AUTO_FORM_CODE,
                form_label=OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
                prefix=OPERATION_ACTION_LOG_REF_PREFIX,
            )
            if not TenantOperationActionLog.objects.filter(log_no=log_no).exists():
                return log_no, log_sequence
        raise ValidationError(
            'Unable to allocate a unique Log No. Please check Auto Number Configuration.'
        )

    @classmethod
    def _find_idempotent_existing(
        cls,
        *,
        idempotency_key: str,
        source_channel: str,
        source_ref: str,
    ) -> TenantOperationActionLog | None:
        if idempotency_key:
            row = TenantOperationActionLog.objects.filter(
                idempotency_key=idempotency_key,
            ).first()
            if row is not None:
                return row
        if source_ref:
            return TenantOperationActionLog.objects.filter(
                source_channel=source_channel,
                source_ref=source_ref,
            ).first()
        return None

    @classmethod
    @transaction.atomic
    def execute_driver_action(
        cls,
        *,
        operation_action,
        log_date=None,
        booking=None,
        shipment=None,
        movement=None,
        truck=None,
        driver=None,
        tenant_user=None,
        created_by_label: str = '',
        notes: str = '',
        source: str = 'Mobile',
        source_channel: str = SOURCE_CHANNEL_MOBILE_DRIVER,
        source_ref: str = '',
        idempotency_key: str = '',
        booking_item_type: str = '',
        latitude: str = '',
        longitude: str = '',
        map_link: str = '',
        birth_booking_item_type: str = '',
        skip_recent_duplicate_guard: bool = False,
        sync_shipment_after: bool = True,
        mobile_cod_amount=None,
    ) -> ActionExecutionResult:
        """
        Mobile-safe action execution: validate → persist log → side effects → optional sync.

        ``SOURCE_CHANNEL_MOBILE_DRIVER`` requires an active
        ``mobile_api.helpers.mobile_execution_guard`` (set by Job Detail execute/POD/COD).
        """
        if (source_channel or '').strip() == SOURCE_CHANNEL_MOBILE_DRIVER:
            from mobile_api.helpers.mobile_execution_guard import (
                assert_mobile_execution_guard_allows,
            )

            assert_mobile_execution_guard_allows(
                driver=driver,
                shipment=shipment,
                movement=movement,
                source_channel=source_channel,
            )

        policy_error = cls.validate_driver_action_execution(
            operation_action,
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
        )
        if policy_error:
            raise ValidationError(policy_error)

        normalized_key = normalize_idempotency_key(idempotency_key)
        normalized_ref = normalize_source_ref(source_ref)
        existing = cls._find_idempotent_existing(
            idempotency_key=normalized_key,
            source_channel=source_channel,
            source_ref=normalized_ref,
        )
        if existing is not None:
            return ActionExecutionResult(action_log=existing, reused_existing=True)

        if not skip_recent_duplicate_guard and not normalized_key:
            dup = find_recent_duplicate(
                shipment=shipment,
                movement=movement,
                operation_action=operation_action,
                created_by_label=created_by_label,
                notes=notes,
                source=source,
            )
            if dup is not None:
                return ActionExecutionResult(action_log=dup, reused_existing=True)

        log_date = log_date or timezone.now()
        log_no, log_sequence = cls._allocate_log_no()

        action_log = TenantOperationActionLog(
            log_no=log_no,
            idempotency_key=(normalized_key or None),
            source_channel=source_channel,
            source_ref=(normalized_ref or ''),
            log_sequence=log_sequence,
            log_date=log_date,
            operation_action=operation_action,
            source=(source or 'Mobile')[:32],
            notes=notes or '',
            booking=booking,
            shipment=shipment,
            truck=truck,
            driver=driver,
            truck_movement=movement,
            latitude=(latitude or '')[:32],
            longitude=(longitude or '')[:32],
            map_link=(map_link or '')[:500],
            created_by=tenant_user,
            created_by_label=(created_by_label or '')[:200],
        )
        if birth_booking_item_type:
            action_log._birth_booking_item_type = birth_booking_item_type.strip()
        if mobile_cod_amount is not None:
            action_log._mobile_cod_amount = mobile_cod_amount

        try:
            action_log.save()
            cls.apply_execution_side_effects(
                action_log,
                created_by_label=created_by_label,
            )
            if sync_shipment_after and action_log.shipment_id:
                shipment_after = action_log.shipment

                status_before_sync = shipment_after.shipment_status

                sync_shipment_status_from_action_log(shipment_after)

                shipment_after.refresh_from_db()
                status_after_sync = shipment_after.shipment_status

                if (
                    status_before_sync == TenantShipment.ShipmentStatus.DELIVERED
                    and status_after_sync
                    == TenantShipment.ShipmentStatus.POD_SUBMITTED
                    and (shipment_after.order_type or '').upper() != 'COD'
                ):
                    shipment_after.shipment_status = (
                        TenantShipment.ShipmentStatus.DELIVERED
                    )
                    shipment_after.save(
                        update_fields=['shipment_status', 'updated_at']
                    )
        except IntegrityError:
            existing = cls._find_idempotent_existing(
                idempotency_key=normalized_key,
                source_channel=source_channel,
                source_ref=normalized_ref,
            )
            if existing is not None:
                return ActionExecutionResult(action_log=existing, reused_existing=True)
            raise

        return ActionExecutionResult(action_log=action_log, reused_existing=False)

    @classmethod
    @transaction.atomic
    def execute_portal_action_log(
        cls,
        *,
        operation_action,
        log_date,
        booking=None,
        shipment=None,
        movement=None,
        truck=None,
        driver=None,
        tenant_user=None,
        created_by_label: str = '',
        notes: str = '',
        source: str = 'Manual',
        source_channel: str = SOURCE_CHANNEL_ADMIN_MANUAL,
        source_ref: str = '',
        idempotency_key: str = '',
        booking_item_type: str = '',
        latitude: str = '',
        longitude: str = '',
        map_link: str = '',
    ) -> ActionExecutionResult:
        """Portal Action Log create — same pipeline as mobile with admin defaults."""
        normalized_key = normalize_idempotency_key(idempotency_key)
        return cls.execute_driver_action(
            operation_action=operation_action,
            log_date=log_date,
            booking=booking,
            shipment=shipment,
            movement=movement,
            truck=truck,
            driver=driver,
            tenant_user=tenant_user,
            created_by_label=created_by_label,
            notes=notes,
            source=source,
            source_channel=source_channel,
            source_ref=source_ref,
            idempotency_key=idempotency_key,
            booking_item_type=booking_item_type,
            latitude=latitude,
            longitude=longitude,
            map_link=map_link,
            birth_booking_item_type=booking_item_type,
            skip_recent_duplicate_guard=bool(normalized_key),
            sync_shipment_after=True,
        )
