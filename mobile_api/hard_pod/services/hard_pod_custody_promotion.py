"""
Promote verified Hard POD custody via tenant Action Master (dynamic codes).

Uses ``ActionExecutionService`` kernel + side effects — not the mobile execute
orchestrator (avoids projection recursion and stale-sync failures).
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

from django.core.exceptions import ValidationError
from django_tenants.utils import schema_context

from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
from iroad_tenants.services.action_execution_service import ActionExecutionService
from mobile_api.helpers.mobile_execution_guard import (
    MobileExecutionContext,
    mobile_execution_guard,
)
from mobile_api.job_detail.guards.ownership import driver_pk
from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    is_hard_pod_action,
)
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    action_code_from_action,
    _iter_active_actions,
)
from mobile_api.helpers.job_action_resolver import resolve_collect_payment_action_code

logger = logging.getLogger('mobile_api.hard_pod')


def _authoritative_shipment_for_custody_submission(
    submission: Any,
    shipment: Any,
    *,
    driver: Any | None = None,
) -> Any:
    """Custody rows are keyed by shipment — never promote on a stale leg."""
    submission_ship_id = str(getattr(submission, 'shipment_id', '') or '').strip()
    schema = str(getattr(submission, 'tenant_schema', '') or '').strip()
    if submission_ship_id:
        from mobile_api.job_detail.guards.entity_lookup import lookup_shipment_by_reference

        try:
            if schema:
                with schema_context(schema):
                    looked_up = lookup_shipment_by_reference(submission_ship_id)
            else:
                looked_up = lookup_shipment_by_reference(submission_ship_id)
        except Exception:
            looked_up = lookup_shipment_by_reference(submission_ship_id)
        if looked_up is not None:
            if driver is not None:
                from mobile_api.helpers.backload_booking_redirect import (
                    coerce_driver_active_shipment_leg,
                )

                return coerce_driver_active_shipment_leg(driver, looked_up) or looked_up
            return looked_up
    if driver is not None:
        from mobile_api.helpers.backload_booking_redirect import (
            coerce_driver_active_shipment_leg,
        )

        return coerce_driver_active_shipment_leg(driver, shipment) or shipment
    return shipment


def resolve_hard_pod_promotion_action(
    tenant_schema: str,
    *,
    shipment: Any | None = None,
) -> Any | None:
    """
    Tenant Action Master row for hard-copy custody promotion execute.

    Combined POD (``auto_pod_post`` + ``hard_copy_collection``) when both flags are set.

    When Hard POD is backend-only (no separate Action Master row), promotion
    re-uses the tenant Upload POD row (e.g. OA-0009) after digital evidence.
    """
    schema = (tenant_schema or '').strip()
    combined = None
    standalone = None
    for action in _iter_active_actions(schema):
        if not getattr(action, 'hard_copy_collection', False):
            continue
        if getattr(action, 'auto_pod_post', False):
            combined = combined or action
            continue
        if standalone is None and is_hard_pod_action(action):
            standalone = action

    if shipment is not None and combined is not None:
        try:
            from iroad_tenants.operation_execution import _digital_pod_step_complete

            if _digital_pod_step_complete(shipment, action=combined):
                return combined
        except Exception:
            return combined

    if shipment is not None:
        from iroad_tenants.operation_field_catalog import (
            operation_shipment_uses_hard_copy_pod,
        )

        if operation_shipment_uses_hard_copy_pod(shipment):
            from mobile_api.pod_capture.services.pod_capture_action_resolver import (
                resolve_digital_pod_action,
            )

            digital = resolve_digital_pod_action(schema)
            if digital is not None:
                try:
                    from iroad_tenants.operation_execution import _digital_pod_step_complete

                    if _digital_pod_step_complete(shipment, action=digital):
                        return digital
                except Exception:
                    return digital

    return standalone or combined


def resolve_hard_pod_promotion_action_code(
    tenant_schema: str,
    *,
    shipment: Any | None = None,
    fallback: str = '',
) -> str:
    action = resolve_hard_pod_promotion_action(
        tenant_schema,
        shipment=shipment,
    )
    return action_code_from_action(action, fallback=fallback)


def promote_custody_submission(
    *,
    submission: Any,
    driver: Any,
    shipment: Any,
    tenant_schema: str,
    payload: Mapping[str, Any] | None = None,
    tenant_user: Any | None = None,
) -> dict[str, Any]:
    """Create/promote hard-copy action log for a verified custody submission."""
    payload = dict(payload or {})
    schema = (tenant_schema or '').strip()
    submission.refresh_from_db()

    if submission.promoted_at and (submission.promotion_action_log_id or '').strip():
        action_code = resolve_hard_pod_promotion_action_code(
            schema,
            shipment=shipment,
        )
        return {
            'promoted': True,
            'replayed': True,
            'action_log_id': str(submission.promotion_action_log_id or ''),
            'execute_action_code': action_code,
        }

    from iroad_tenants.operation_runtime.latest_state import (
        repair_shipment_status_before_hard_pod_promotion,
    )

    with schema_context(schema):
        shipment = _authoritative_shipment_for_custody_submission(
            submission,
            shipment,
            driver=driver,
        )
        repair_shipment_status_before_hard_pod_promotion(shipment)
        operation_action = resolve_hard_pod_promotion_action(schema, shipment=shipment)
    if operation_action is None:
        logger.warning('hard_pod_promotion_no_action tenant=%s shipment=%s', schema, getattr(shipment, 'pk', ''))
        return {
            'promoted': False,
            'error_code': 'hard_pod_action_not_configured',
            'message_key': 'mobile.hard_pod.action_not_configured',
        }

    action_code = action_code_from_action(operation_action, fallback='')
    shipment_pk = str(
        getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', '') or ''
    ).strip()
    driver_id = str(driver_pk(driver) or '').strip()
    client_submission_id = str(
        getattr(submission, 'client_submission_id', None) or ''
    ).strip()
    submission_pk = str(getattr(submission, 'pk', '') or '').strip()
    idempotency_key = f'hard-pod-promote-{client_submission_id or submission_pk}'

    guard_ctx = MobileExecutionContext(
        driver=driver,
        tenant_user=tenant_user,
        tenant_schema=schema,
        driver_id=driver_id,
        user_id=str(getattr(driver, 'user_id', '') or driver_id),
        jwt_driver_id=driver_id,
    )

    created_by_label = str(
        getattr(driver, 'driver_no', None)
        or getattr(driver, 'driver_code', None)
        or getattr(driver, 'english_name', None)
        or driver_id
    )[:200]

    try:
        with schema_context(schema):
            with mobile_execution_guard(guard_ctx):
                result = ActionExecutionService.execute_driver_action(
                    operation_action=operation_action,
                    shipment=shipment,
                    driver=driver,
                    tenant_user=tenant_user,
                    created_by_label=created_by_label,
                    notes=str(payload.get('handoff_notes') or payload.get('notes') or '').strip(),
                    source='Mobile',
                    source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                    source_ref=client_submission_id,
                    idempotency_key=idempotency_key,
                    latitude=str(payload.get('latitude') or getattr(submission, 'latitude', '') or '').strip(),
                    longitude=str(payload.get('longitude') or getattr(submission, 'longitude', '') or '').strip(),
                    hard_pod_custody_submission_id=submission_pk,
                    hard_pod_client_submission_id=client_submission_id,
                )
    except ValidationError as exc:
        message = str(exc)
        if hasattr(exc, 'message_dict'):
            try:
                message = '; '.join(
                    f'{k}: {v}' for k, v in exc.message_dict.items()
                )
            except Exception:
                pass
        code = getattr(exc, 'code', None) or 'hard_pod_execute_validation_failed'
        logger.warning(
            'hard_pod_kernel_promotion_failed code=%s shipment=%s submission=%s msg=%s',
            code,
            shipment_pk,
            submission_pk,
            message,
        )
        return {
            'promoted': False,
            'execute_action_code': action_code,
            'error_code': str(code),
            'message': message,
            'message_key': 'mobile.hard_pod.execute_failed',
        }
    except Exception:
        logger.exception(
            'hard_pod_kernel_promotion_unexpected shipment=%s submission=%s',
            shipment_pk,
            submission_pk,
        )
        return {
            'promoted': False,
            'execute_action_code': action_code,
            'error_code': 'hard_pod_execute_failed',
            'message_key': 'mobile.hard_pod.execute_failed',
        }

    submission.refresh_from_db()
    action_log = result.action_log
    action_log_id = str(
        submission.promotion_action_log_id
        or getattr(action_log, 'log_id', None)
        or getattr(action_log, 'pk', '')
        or ''
    ).strip()
    promoted = bool(
        submission.promoted_at
        and (submission.promotion_action_log_id or '').strip()
    )
    out: dict[str, Any] = {
        'promoted': promoted,
        'replayed': bool(result.reused_existing),
        'execute_action_code': action_code,
        'action_log_id': action_log_id,
    }
    if promoted:
        cod_code = resolve_collect_payment_action_code(schema)
        if cod_code:
            out['next_collect_payment_action_code'] = cod_code
    return out
