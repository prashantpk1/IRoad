"""
Production Action Master catalog for mobile COD/Credit job workflow.

Single source of truth for seeding, validation, and auto-verify action resolution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from iroad_tenants.operation_runtime.impacts import resolve_shipment_status_impact
from tenant_workspace.models import TenantOperationAction, TenantOperationActionLog, TenantShipment

AUTO_COD_VERIFY_CHANNEL = 'auto_cod_verify'
AUTO_COD_VERIFY_ACTION_CODE = 'A_POD_VERIFY'
AUTO_COD_VERIFY_IDEMPOTENCY_PREFIX = 'auto-pod-verify-'
AUTO_COD_VERIFY_LOG_NO_PREFIX = 'LOG-POD-VERIFY-'
AUTO_COD_VERIFY_ENGLISH_LABEL = 'POD Verified'
AUTO_COD_VERIFY_ARABIC_LABEL = 'تم التحقق من POD'
SYSTEM_AUTO_POD_VERIFY_CHANNELS = frozenset(
    {
        AUTO_COD_VERIFY_CHANNEL,
        'auto_pod_verify',
        'mobile_job_close_ready',
    },
)


def is_system_auto_pod_verify_channel(channel: str) -> bool:
    """Backend-only POD verify logs — no Action Master row required."""
    return (channel or '').strip() in SYSTEM_AUTO_POD_VERIFY_CHANNELS


def exclude_admin_hidden_system_logs(qs):
    """Hide backend-only auto POD verify reconciler rows from tenant admin lists."""
    from django.db.models import Q

    return qs.exclude(
        Q(source_channel__in=SYSTEM_AUTO_POD_VERIFY_CHANNELS)
        | Q(log_no__startswith=AUTO_COD_VERIFY_LOG_NO_PREFIX)
        | Q(idempotency_key__startswith=AUTO_COD_VERIFY_IDEMPOTENCY_PREFIX)
    )


@dataclass(frozen=True)
class ActionMasterSpec:
    action_code: str
    english_label: str
    arabic_label: str
    sequence_number: int
    auto_movement_post: bool = False
    auto_shipment_post: bool = False
    auto_pod_post: bool = False
    auto_treasury_post: bool = False
    hard_copy_collection: bool = False
    mobile_visible: bool = True
    admin_only: bool = False
    booking_status_impact: str = ''
    shipment_status_impact: str = ''
    movement_status_impact: str = ''
    prerequisite_action_codes: tuple[str, ...] = ()
    condition_code: str = ''
    action_scope: str = 'job'
    sequence_category: str = 'job'
    status: str = 'Active'

    def defaults(self, model_fields: set[str]) -> dict[str, Any]:
        values: dict[str, Any] = {
            'english_label': self.english_label,
            'arabic_label': self.arabic_label,
            'status': self.status,
            'action_scope': self.action_scope,
            'sequence_category': self.sequence_category,
            'sequence_number': self.sequence_number,
            'auto_movement_post': self.auto_movement_post,
            'auto_shipment_post': self.auto_shipment_post,
            'auto_pod_post': self.auto_pod_post,
            'auto_treasury_post': self.auto_treasury_post,
            'hard_copy_collection': self.hard_copy_collection,
            'mobile_visible': self.mobile_visible,
            'admin_only': self.admin_only,
            'booking_status_impact': self.booking_status_impact,
            'shipment_status_impact': self.shipment_status_impact,
            'movement_status_impact': self.movement_status_impact,
            'prerequisite_action_codes': ','.join(self.prerequisite_action_codes),
            'condition_code': self.condition_code,
        }
        return {field: value for field, value in values.items() if field in model_fields}


PRODUCTION_ACTION_MASTER: tuple[ActionMasterSpec, ...] = (
    ActionMasterSpec(
        action_code='A1',
        english_label='Start Job',
        arabic_label='Start Job',
        sequence_number=1,
        booking_status_impact='In_Execution',
    ),
    ActionMasterSpec(
        action_code='A2',
        english_label='Pickup Arrival',
        arabic_label='Pickup Arrival',
        sequence_number=2,
        prerequisite_action_codes=('A1',),
    ),
    ActionMasterSpec(
        action_code='A3',
        english_label='Start Loading',
        arabic_label='Start Loading',
        sequence_number=3,
        prerequisite_action_codes=('A2',),
    ),
    ActionMasterSpec(
        action_code='A4',
        english_label='Confirm Loaded',
        arabic_label='Confirm Loaded',
        sequence_number=4,
        auto_shipment_post=True,
        auto_movement_post=True,
        booking_status_impact='In_Execution',
        shipment_status_impact='Loaded',
        movement_status_impact='Scheduled',
        prerequisite_action_codes=('A3',),
    ),
    ActionMasterSpec(
        action_code='A5',
        english_label='Depart In Transit',
        arabic_label='Depart In Transit',
        sequence_number=5,
        shipment_status_impact='In_Transit',
        movement_status_impact='In_Progress',
        prerequisite_action_codes=('A4',),
    ),
    ActionMasterSpec(
        action_code='A6',
        english_label='Delivery Arrival',
        arabic_label='Delivery Arrival',
        sequence_number=6,
        shipment_status_impact='At_Delivery',
        prerequisite_action_codes=('A5',),
    ),
    ActionMasterSpec(
        action_code='A7',
        english_label='Upload POD',
        arabic_label='Upload POD',
        sequence_number=7,
        auto_pod_post=True,
        shipment_status_impact='POD_Submitted',
        prerequisite_action_codes=('A6',),
    ),
    ActionMasterSpec(
        action_code='A8',
        english_label='Unloading Completed',
        arabic_label='Unloading Completed',
        sequence_number=8,
        movement_status_impact='Completed',
        prerequisite_action_codes=('A7',),
    ),
    ActionMasterSpec(
        action_code='A9',
        english_label='Collect Payment',
        arabic_label='Collect Payment',
        sequence_number=9,
        auto_treasury_post=True,
        prerequisite_action_codes=('A7',),
        condition_code='Order_Type_must_be_COD',
    ),
    ActionMasterSpec(
        action_code='A10',
        english_label='Job Closed',
        arabic_label='Job Closed',
        sequence_number=10,
        booking_status_impact='Executed',
        shipment_status_impact='Closed',
        prerequisite_action_codes=('A8', 'A9'),
        condition_code='A9_required_if_COD',
    ),
)

# Legacy EM* codes — runtime fallbacks only; never auto-seeded (tenant defines empty_move rows).
LEGACY_EMPTY_MOVE_ACTION_CODES = frozenset({'EM1', 'EM2', 'EM3', 'EM4'})
EMPTY_MOVE_ACTION_CODES = LEGACY_EMPTY_MOVE_ACTION_CODES

# PDF Table 10/11 — tenant-defined in Operation Action Master (never auto-seeded).
WITHOUT_SCOPE_CANCEL_SHIPMENT_LABEL = 'Cancel Shipment'
WITHOUT_SCOPE_CANCEL_BOOKING_ITEM_LABEL = 'Cancel Booking Item'
WITHOUT_SCOPE_CANCEL_BOOKING_LABEL = 'Cancel Booking'
WITHOUT_SCOPE_REJECT_POD_LABEL = 'Reject POD'
WITHOUT_SCOPE_CANCEL_MOVEMENT_LABEL = 'Cancel Movement'
WITHOUT_SCOPE_INCIDENT_REPORT_LABEL = 'Incident Report'


WITHOUT_SCOPE_MARKER = 'without'


def active_without_scope_action_options():
    """Active Operation Action rows with scope/category ``without`` (admin reversals)."""
    from django.db.models import Q

    return TenantOperationAction.objects.filter(
        status=TenantOperationAction.Status.ACTIVE,
    ).filter(
        Q(action_scope=WITHOUT_SCOPE_MARKER)
        | Q(sequence_category=WITHOUT_SCOPE_MARKER),
    ).order_by('sequence_number', 'action_code')


def _active_without_scope_actions(*, english_label: str):
    """Active Operation Action rows for a without-scope English label."""
    from django.db.models import Q

    label = (english_label or '').strip()
    if not label:
        return TenantOperationAction.objects.none()

    base = TenantOperationAction.objects.filter(
        status=TenantOperationAction.Status.ACTIVE,
        english_label__iexact=label,
    )
    scoped = base.filter(
        Q(action_scope=WITHOUT_SCOPE_MARKER)
        | Q(sequence_category=WITHOUT_SCOPE_MARKER)
    ).order_by('sequence_number', 'action_code')
    if scoped.exists():
        return scoped
    return base.order_by('sequence_number', 'action_code')


def resolve_without_scope_action(
    *,
    english_label: str,
    legacy_action_codes: tuple[str, ...] = (),
) -> TenantOperationAction | None:
    """
    Resolve a tenant-configured ``without``-scope Operation Action.

    Never auto-creates rows — admins define these in Operation Action Master
    (PDF Tables 10/11, e.g. OA-0017..OA-0021).

    Resolution order:
      1. Legacy action codes (R1, R2, …) when still present in tenant data.
      2. Active row matching English label with scope/category ``without``.
      3. Active row matching English label only (single match).
    """
    for code in legacy_action_codes:
        row = TenantOperationAction.objects.filter(
            action_code__iexact=code,
            status=TenantOperationAction.Status.ACTIVE,
        ).first()
        if row is not None:
            return row

    label = (english_label or '').strip()
    if not label:
        return None

    scoped = _active_without_scope_actions(english_label=label)
    if scoped.count() == 1:
        return scoped.first()
    if scoped.count() > 1:
        return scoped.first()

    fallback = TenantOperationAction.objects.filter(
        status=TenantOperationAction.Status.ACTIVE,
        english_label__iexact=label,
    ).order_by('sequence_number', 'action_code')
    if fallback.count() == 1:
        return fallback.first()
    return fallback.first() if fallback.exists() else None


def cancel_action_configuration_error(english_label: str) -> str:
    return (
        f'Operation Action "{english_label}" is not configured. '
        'Create an Active Operation Action with Action Scope "Without", '
        f'English label "{english_label}", and Shipment Status Impact "Cancelled".'
    )


def resolve_cancel_shipment_action() -> TenantOperationAction | None:
    return resolve_without_scope_action(
        english_label=WITHOUT_SCOPE_CANCEL_SHIPMENT_LABEL,
        legacy_action_codes=('R1',),
    )


def resolve_cancel_booking_item_action() -> TenantOperationAction | None:
    return resolve_without_scope_action(
        english_label=WITHOUT_SCOPE_CANCEL_BOOKING_ITEM_LABEL,
        legacy_action_codes=('R2',),
    )


def resolve_cancel_booking_action() -> TenantOperationAction | None:
    return resolve_without_scope_action(
        english_label=WITHOUT_SCOPE_CANCEL_BOOKING_LABEL,
        legacy_action_codes=('R3',),
    )


def resolve_reject_pod_action() -> TenantOperationAction | None:
    return resolve_without_scope_action(
        english_label=WITHOUT_SCOPE_REJECT_POD_LABEL,
        legacy_action_codes=('R4',),
    )


def resolve_cancel_movement_action() -> TenantOperationAction | None:
    return resolve_without_scope_action(
        english_label=WITHOUT_SCOPE_CANCEL_MOVEMENT_LABEL,
    )


def resolve_incident_report_action() -> TenantOperationAction | None:
    return resolve_without_scope_action(
        english_label=WITHOUT_SCOPE_INCIDENT_REPORT_LABEL,
    )


def resolve_auto_close_job_action() -> TenantOperationAction | None:
    """Resolve Action Master job-close row (dynamic — not fixed A10/OA-0010)."""
    from iroad_tenants.operation_runtime.workflow_action_policy import (
        resolve_job_close_operation_action,
    )

    return resolve_job_close_operation_action()


def validate_production_action_master() -> list[str]:
    """Return human-readable configuration errors (empty = production-ready)."""
    errors: list[str] = []
    by_code = {
        (row.action_code or '').strip().upper(): row
        for row in TenantOperationAction.objects.all()
    }

    for spec in PRODUCTION_ACTION_MASTER:
        code = spec.action_code.upper()
        row = by_code.get(code)
        if row is None:
            errors.append(f'Missing action: {spec.action_code}')
            continue
        if row.status != TenantOperationAction.Status.ACTIVE:
            errors.append(f'{spec.action_code}: status must be Active (got {row.status})')
        if spec.shipment_status_impact:
            resolved = resolve_shipment_status_impact(row.shipment_status_impact)
            expected = resolve_shipment_status_impact(spec.shipment_status_impact)
            if resolved != expected:
                errors.append(
                    f'{spec.action_code}: shipment_status_impact must resolve to '
                    f'{expected!r} (got {row.shipment_status_impact!r})',
                )
        if row.mobile_visible != spec.mobile_visible:
            errors.append(
                f'{spec.action_code}: mobile_visible must be {spec.mobile_visible}',
            )
    return errors


def repair_auto_cod_verify_logs(*, dry_run: bool = False) -> int:
    """
    Clear mistaken Action Master links on backend auto POD verify logs.

    Auto verify is log-only (``operation_action`` NULL); legacy rows may still
    point at A6 or other mis-attached actions.
    """
    wrong_qs = TenantOperationActionLog.objects.filter(
        source_channel__in=SYSTEM_AUTO_POD_VERIFY_CHANNELS,
    ).exclude(operation_action__isnull=True)

    count = wrong_qs.count()
    if count and not dry_run:
        wrong_qs.update(operation_action=None)
    return count
