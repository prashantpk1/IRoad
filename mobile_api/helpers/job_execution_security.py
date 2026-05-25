"""
mobile_api/helpers/job_execution_security.py

Multi-tenant security for driver **job execution** (POST execute, POD, COD).

Every execution path must:
- Bind JWT tenant + driver row (via ``resolve_secure_job_list_context``).
- Load shipment/movement only through driver-scoped querysets (IDOR-safe).
- Resolve operation actions as **Active** tenant rows only (secure lookup).
- Enforce workflow policy via ``OperationExecutionService.validate_driver_action_execution``.
- Optionally require ``action_id`` membership in ``get_allowed_driver_actions`` (tampering guard).
- Emit structured security audit events on violations (no secrets / JWTs).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from django.conf import settings
from django.utils.translation import gettext as _

from mobile_api.helpers.job_list_security import (
    JOBS_API_PREFIX,
    SecureJobListContext,
    assert_driver_owns_movement,
    assert_driver_owns_shipment,
    resolve_secure_job_list_context,
    validate_jobs_tenant_binding,
)
from mobile_api.helpers.security_audit import (
    client_ip_from_request,
    log_mobile_security_event,
)
from mobile_api.rbac import get_mobile_jwt_payload, request_has_capability
from mobile_api.services.driver_job_allowed_actions_service import (
    DriverJobAllowedActionsService,
)
from mobile_api.services.job_detail_snapshot_service import JobDetailSnapshotService
from tenant_workspace.models import TenantOperationAction

logger = logging.getLogger('mobile_api')

JOBS_EXECUTE_CAPABILITY = 'mobile.driver.jobs.execute'
JOBS_READ_CAPABILITY = 'mobile.driver.jobs'

# POST routes under ``/api/v1/mobile/driver/jobs/`` (middleware + docs).
JOB_EXECUTION_POST_MARKERS = (
    '/actions/execute/',
    '/upload-pod/',
    '/collect-cod/',
)

JobExecutionEntity = Literal['shipment', 'movement']


@dataclass(frozen=True)
class SecureJobExecutionContext(SecureJobListContext):
    """Bound principal for one execution request (extends job-list context)."""

    jwt_payload: dict | None = None


def jobs_execution_action_membership_enabled() -> bool:
    """
    Tamper guard is **mandatory** outside DEBUG.

    ``MOBILE_API_JOBS_ENFORCE_ACTION_MEMBERSHIP=False`` only disables the guard
    when ``DEBUG=True`` (local dev). In production (``DEBUG=False``) membership
    is always enforced.
    """
    if bool(getattr(settings, 'MOBILE_API_JOBS_ENFORCE_ACTION_MEMBERSHIP', True)):
        return True
    try:
        from django.conf import settings as dj_settings

        return not bool(getattr(dj_settings, 'DEBUG', False))
    except Exception:
        return True


def jobs_execution_audit_enabled() -> bool:
    return bool(
        getattr(settings, 'MOBILE_API_JOBS_EXECUTION_AUDIT_ENABLED', True)
    )


def is_jobs_execution_post_path(path: str) -> bool:
    """True when path is a driver job **mutation** endpoint (execute / POD / COD)."""
    p = (path or '').strip()
    if not p.startswith(JOBS_API_PREFIX):
        return False
    return any(marker in p for marker in JOB_EXECUTION_POST_MARKERS)


def validate_jobs_execution_tenant_binding(request, *, expected_schema: str) -> bool:
    """Same binding rules as job list — JWT schema must match tenant hints."""
    return validate_jobs_tenant_binding(request, expected_schema=expected_schema)


def execution_context_required_error() -> dict[str, Any]:
    """Standard API error when ``SecureJobExecutionContext`` is missing."""
    return {
        'success': False,
        'code': 'execution_context_required',
        'error': _('mobile.jobs.execute.execution_context_required'),
    }


def validate_execution_context_binding(
    ctx: SecureJobExecutionContext,
    *,
    driver,
    tenant_user=None,
    request=None,
) -> dict[str, Any] | None:
    """
    Ensure the resolved context matches the execution principal (anti-spoof).
    """
    ctx_driver = getattr(ctx, 'driver_id', None) or str(
        getattr(getattr(ctx, 'driver', None), 'pk', '') or ''
    )
    call_driver = str(
        getattr(driver, 'driver_id', None) or getattr(driver, 'pk', '') or ''
    )
    if ctx_driver and call_driver and ctx_driver != call_driver:
        _audit_execution_violation(
            ctx,
            event='execution_context_driver_mismatch',
            reason=f'ctx={ctx_driver[:36]} call={call_driver[:36]}',
            request=request,
        )
        return {
            'success': False,
            'code': 'execution_context_invalid',
            'error': _('mobile.jobs.execute.execution_context_driver_mismatch'),
        }

    if tenant_user is not None:
        ctx_user = str(getattr(ctx, 'user_id', '') or '')
        call_user = str(
            getattr(tenant_user, 'user_id', None)
            or getattr(tenant_user, 'pk', '')
            or ''
        )
        if ctx_user and call_user and ctx_user != call_user:
            _audit_execution_violation(
                ctx,
                event='execution_context_user_mismatch',
                reason=f'ctx={ctx_user[:36]} call={call_user[:36]}',
                request=request,
            )
            return {
                'success': False,
                'code': 'execution_context_invalid',
                'error': _('mobile.jobs.execute.execution_context_user_mismatch'),
            }

    if not (ctx.tenant_schema or '').strip():
        return execution_context_required_error()

    return None


def require_execution_context(
    ctx: SecureJobExecutionContext | None,
    *,
    driver=None,
    tenant_user=None,
    request=None,
) -> dict[str, Any] | None:
    """
    Mandatory execution context gate for Job Detail mutations.

    Returns an error dict when missing/invalid; ``None`` when OK.
    """
    if ctx is None:
        if request is not None:
            try:
                log_mobile_security_event(
                    'execution_context_missing',
                    schema='',
                    user_id='',
                    ip=client_ip_from_request(request),
                    reason='ctx_none',
                )
            except Exception:
                pass
        return execution_context_required_error()

    binding_err = validate_execution_context_binding(
        ctx,
        driver=driver,
        tenant_user=tenant_user,
        request=request,
    )
    return binding_err


def resolve_secure_job_execution_context(
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    jwt_payload: dict | None = None,
    preload_ownership: bool | None = None,
) -> dict[str, Any]:
    """
    Load driver + tenant invariants for execution (delegates to job-list resolver).
    """
    base = resolve_secure_job_list_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        request=request,
        jwt_payload=jwt_payload,
        preload_ownership=preload_ownership,
    )
    if not base.get('success'):
        return base

    list_ctx = base['ctx']
    pl = jwt_payload if jwt_payload is not None else (
        get_mobile_jwt_payload(request) if request is not None else {}
    )
    ctx = SecureJobExecutionContext(
        driver=list_ctx.driver,
        tenant_user=list_ctx.tenant_user,
        tenant_schema=list_ctx.tenant_schema,
        driver_id=list_ctx.driver_id,
        user_id=list_ctx.user_id,
        jwt_driver_id=list_ctx.jwt_driver_id,
        ownership_scope=list_ctx.ownership_scope,
        jwt_payload=pl if isinstance(pl, dict) else {},
    )
    return {'success': True, 'ctx': ctx}


def _normalize_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _audit_execution_violation(
    ctx: SecureJobExecutionContext,
    *,
    event: str,
    reason: str,
    request=None,
) -> None:
    if not jobs_execution_audit_enabled():
        return
    try:
        log_mobile_security_event(
            event,
            schema=ctx.tenant_schema,
            user_id=ctx.user_id,
            ip=client_ip_from_request(request),
            reason=reason[:200],
        )
    except Exception:
        pass
    logger.warning(
        'job_execution_security event=%s schema=%s driver_id=%s reason=%s',
        event,
        ctx.tenant_schema,
        ctx.driver_id,
        reason[:120],
    )


def secure_lookup_operation_action(
    action_id,
    *,
    ctx: SecureJobExecutionContext,
    request=None,
) -> TenantOperationAction | None:
    """
    Tenant-scoped action lookup — only **Active** rows; never trust stale/inactive IDs.

    Requires a bound ``SecureJobExecutionContext`` (no anonymous lookup on execute paths).
    """
    binding_err = require_execution_context(ctx, request=request)
    if binding_err is not None:
        return None

    parsed = _normalize_uuid(str(action_id) if action_id is not None else '')
    if not parsed:
        _audit_execution_violation(
            ctx,
            event='execution_invalid_action_id',
            reason='bad_uuid',
            request=request,
        )
        return None
    action = (
        TenantOperationAction.objects.filter(
            pk=parsed,
            status=TenantOperationAction.Status.ACTIVE,
        )
        .first()
    )
    if action is None:
        _audit_execution_violation(
            ctx,
            event='execution_action_not_found',
            reason=f'action_id={parsed[:36]}',
            request=request,
        )
    return action


def secure_load_shipment_for_execution(
    ctx: SecureJobExecutionContext,
    shipment_id: str,
    *,
    request=None,
) -> Any | None:
    parsed = _normalize_uuid(shipment_id)
    if not parsed:
        return None
    row = JobDetailSnapshotService._load_shipment(
        driver=ctx.driver,
        shipment_id=parsed,
    )
    if row is None:
        _audit_execution_violation(
            ctx,
            event='execution_shipment_idor',
            reason=f'shipment_id={parsed[:36]}',
            request=request,
        )
        return None
    if not assert_driver_owns_shipment(
        ctx.driver,
        row,
        scope=ctx.ownership_scope,
    ):
        _audit_execution_violation(
            ctx,
            event='execution_shipment_ownership_denied',
            reason=f'shipment_id={parsed[:36]}',
            request=request,
        )
        return None
    return row


def secure_load_movement_for_execution(
    ctx: SecureJobExecutionContext,
    movement_id: str,
    *,
    request=None,
) -> Any | None:
    parsed = _normalize_uuid(movement_id)
    if not parsed:
        return None
    row = JobDetailSnapshotService._load_movement(
        driver=ctx.driver,
        movement_id=parsed,
    )
    if row is None:
        _audit_execution_violation(
            ctx,
            event='execution_movement_idor',
            reason=f'movement_id={parsed[:36]}',
            request=request,
        )
        return None
    if not assert_driver_owns_movement(
        ctx.driver,
        row,
        scope=ctx.ownership_scope,
    ):
        _audit_execution_violation(
            ctx,
            event='execution_movement_ownership_denied',
            reason=f'movement_id={parsed[:36]}',
            request=request,
        )
        return None
    return row


def _allowed_action_id_set(
    *,
    driver,
    shipment,
    movement,
    request=None,
) -> set[str]:
    from mobile_api.helpers.execution_workflow_cache import (
        allowed_action_ids_from_payload,
        get_allowed_driver_actions_cached,
    )

    booking, shipment, movement, booking_item_type = (
        DriverJobAllowedActionsService._resolve_linkage(
            shipment=shipment,
            movement=movement,
        )
    )
    job_type = 'shipment' if shipment is not None else 'movement'
    job_id = str(shipment.shipment_id) if shipment else str(movement.movement_id)
    job_no = shipment.shipment_no if shipment else movement.movement_no

    payload = get_allowed_driver_actions_cached(
        request,
        driver=driver,
        booking=booking,
        shipment=shipment,
        movement=movement,
        booking_item_type=booking_item_type,
        job_type=job_type,
        job_id=job_id,
        job_no=job_no,
    )
    return allowed_action_ids_from_payload(payload)


def enforce_action_membership_in_allowed_set(
    operation_action: TenantOperationAction,
    *,
    ctx: SecureJobExecutionContext,
    shipment,
    movement,
    request=None,
) -> str | None:
    """
    Tampering guard: client ``action_id`` must appear in engine allowed-actions list.

    Returns error message when denied; ``None`` when allowed or check disabled.
    """
    if not jobs_execution_action_membership_enabled():
        return None

    allowed_ids = _allowed_action_id_set(
        driver=ctx.driver,
        shipment=shipment,
        movement=movement,
        request=request,
    )
    action_pk = str(operation_action.pk)
    if action_pk in allowed_ids:
        return None

    _audit_execution_violation(
        ctx,
        event='execution_action_not_in_allowed_set',
        reason=f'action_id={action_pk[:36]} code={operation_action.action_code}',
        request=request,
    )
    return _('mobile.jobs.execute.action_not_allowed')


def authorize_driver_action_execution(
    operation_action: TenantOperationAction,
    *,
    ctx: SecureJobExecutionContext,
    shipment,
    movement,
    request=None,
    client_action_id=None,
) -> dict[str, Any]:
    """
    Full execution authorization chain (ownership assumed on entities).

    Returns ``{'success': True}`` or ``{'success': False, 'code', 'error'}``.
    """
    from iroad_tenants.services.operation_execution_service import (
        OperationExecutionService,
    )

    if client_action_id is not None:
        client_parsed = _normalize_uuid(str(client_action_id))
        if client_parsed and client_parsed != str(operation_action.pk):
            _audit_execution_violation(
                ctx,
                event='execution_action_id_mismatch',
                reason=f'client={client_parsed[:36]} resolved={str(operation_action.pk)[:36]}',
                request=request,
            )
            return {
                'success': False,
                'code': 'invalid_action',
                'error': _('mobile.jobs.execute.invalid_action'),
            }

    membership_error = enforce_action_membership_in_allowed_set(
        operation_action,
        ctx=ctx,
        shipment=shipment,
        movement=movement,
        request=request,
    )
    if membership_error:
        return {
            'success': False,
            'code': 'action_not_allowed',
            'error': membership_error,
        }

    booking, shipment, movement, booking_item_type = (
        DriverJobAllowedActionsService._resolve_linkage(
            shipment=shipment,
            movement=movement,
        )
    )
    policy_error = OperationExecutionService.validate_driver_action_execution(
        operation_action,
        booking=booking,
        shipment=shipment,
        movement=movement,
        booking_item_type=booking_item_type,
    )
    if policy_error:
        _audit_execution_violation(
            ctx,
            event='execution_policy_denied',
            reason=f'{operation_action.action_code}:{str(policy_error)[:80]}',
            request=request,
        )
        return {
            'success': False,
            'code': 'action_not_allowed',
            'error': policy_error,
        }

    return {'success': True}


def assert_action_log_owned_by_driver(
    driver,
    action_log,
    *,
    ctx: SecureJobExecutionContext | None = None,
    request=None,
) -> bool:
    """Prevent cross-driver audit/log IDOR when attaching media or reading logs."""
    if action_log is None:
        return False
    row_driver_id = getattr(action_log, 'driver_id', None)
    driver_pk = getattr(driver, 'pk', None)
    if row_driver_id is None:
        return True
    if row_driver_id == driver_pk:
        return True
    if ctx is not None:
        _audit_execution_violation(
            ctx,
            event='execution_action_log_driver_mismatch',
            reason=f'log_id={str(getattr(action_log, "log_id", ""))[:36]}',
            request=request,
        )
    return False


def request_may_execute_driver_actions(request) -> bool:
    return request_has_capability(request, JOBS_EXECUTE_CAPABILITY)


def request_may_upload_pod(request) -> bool:
    return request_may_execute_driver_actions(request) or request_has_capability(
        request,
        'mobile.driver.quick_action.upload_pod',
    )


def request_may_collect_cod(request) -> bool:
    return request_may_execute_driver_actions(request) or request_has_capability(
        request,
        'mobile.driver.quick_action.cod_collection',
    )


def strip_execution_audit_tamper_fields(data: dict) -> dict:
    """
    Remove client attempts to override audit/driver identity on execution payloads.
    """
    if not isinstance(data, dict):
        return {}
    blocked = frozenset({
        'driver_id',
        'created_by',
        'created_by_id',
        'log_id',
        'log_no',
        'tenant_schema',
        'tenant_id',
        'user_id',
    })
    return {k: v for k, v in data.items() if k not in blocked}


__all__ = [
    'JOBS_EXECUTE_CAPABILITY',
    'JOBS_READ_CAPABILITY',
    'JOB_EXECUTION_POST_MARKERS',
    'JobExecutionEntity',
    'SecureJobExecutionContext',
    'assert_action_log_owned_by_driver',
    'authorize_driver_action_execution',
    'enforce_action_membership_in_allowed_set',
    'execution_context_required_error',
    'is_jobs_execution_post_path',
    'jobs_execution_action_membership_enabled',
    'jobs_execution_audit_enabled',
    'request_may_collect_cod',
    'request_may_execute_driver_actions',
    'request_may_upload_pod',
    'require_execution_context',
    'resolve_secure_job_execution_context',
    'validate_execution_context_binding',
    'secure_load_movement_for_execution',
    'secure_load_shipment_for_execution',
    'secure_lookup_operation_action',
    'strip_execution_audit_tamper_fields',
    'validate_jobs_execution_tenant_binding',
]
