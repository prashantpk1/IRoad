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
        action_code='A7H',
        english_label='Hard POD Collection',
        arabic_label='Hard POD Collection',
        sequence_number=72,
        hard_copy_collection=True,
        # Hard copy is a sub-step inside Upload POD (A7), not a separate timeline row.
        mobile_visible=False,
        prerequisite_action_codes=('A7',),
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
    ActionMasterSpec(
        action_code=AUTO_COD_VERIFY_ACTION_CODE,
        english_label='POD Verified',
        arabic_label='POD Verified',
        sequence_number=75,
        mobile_visible=False,
        admin_only=False,
        shipment_status_impact='Delivered',
        action_scope='job',
        sequence_category='',
    ),
    ActionMasterSpec(
        action_code='EM1',
        english_label='Start Movement',
        arabic_label='Start Movement',
        sequence_number=1,
        movement_status_impact='In_Progress',
        action_scope='job',
        sequence_category='empty_move',
    ),
    ActionMasterSpec(
        action_code='EM2',
        english_label='Depart Empty',
        arabic_label='Depart Empty',
        sequence_number=2,
        prerequisite_action_codes=('EM1',),
        action_scope='job',
        sequence_category='empty_move',
    ),
    ActionMasterSpec(
        action_code='EM3',
        english_label='Arrival At Destination',
        arabic_label='Arrival At Destination',
        sequence_number=3,
        prerequisite_action_codes=('EM2',),
        action_scope='job',
        sequence_category='empty_move',
    ),
    ActionMasterSpec(
        action_code='EM4',
        english_label='Complete Movement',
        arabic_label='Complete Movement',
        sequence_number=4,
        movement_status_impact='Completed',
        prerequisite_action_codes=('EM3',),
        action_scope='job',
        sequence_category='empty_move',
    ),
    ActionMasterSpec(
        action_code='R1',
        english_label='Cancel Shipment',
        arabic_label='Cancel Shipment',
        sequence_number=1,
        mobile_visible=False,
        admin_only=True,
        action_scope='without',
        sequence_category='without',
    ),
    ActionMasterSpec(
        action_code='R2',
        english_label='Cancel Booking Item',
        arabic_label='Cancel Booking Item',
        sequence_number=2,
        mobile_visible=False,
        admin_only=True,
        action_scope='without',
        sequence_category='without',
    ),
    ActionMasterSpec(
        action_code='R3',
        english_label='Cancel Booking',
        arabic_label='Cancel Booking',
        sequence_number=3,
        mobile_visible=False,
        admin_only=True,
        action_scope='without',
        sequence_category='without',
    ),
    ActionMasterSpec(
        action_code='R4',
        english_label='Reject POD',
        arabic_label='Reject POD',
        sequence_number=4,
        mobile_visible=False,
        admin_only=True,
        action_scope='without',
        sequence_category='without',
    ),
)

_EXCLUDED_FALLBACK_CODES = frozenset(
    {'A6', 'A7', 'A8', 'A9', 'A10', 'A1', 'A2', 'A3', 'A4', 'A5'},
)


def resolve_auto_cod_verify_action() -> TenantOperationAction | None:
    """
    Resolve the Action Master row used for post-A9 auto POD verify logs.

    Never use ``icontains='Deliver'`` — that incorrectly matches ``At_Delivery`` (A6).
    """
    verify = TenantOperationAction.objects.filter(
        action_code__iexact=AUTO_COD_VERIFY_ACTION_CODE,
        status=TenantOperationAction.Status.ACTIVE,
    ).first()
    if verify is not None:
        impact = resolve_shipment_status_impact(verify.shipment_status_impact)
        if impact == TenantShipment.ShipmentStatus.DELIVERED:
            return verify

    for row in TenantOperationAction.objects.filter(
        status=TenantOperationAction.Status.ACTIVE,
    ).exclude(
        action_code__in=_EXCLUDED_FALLBACK_CODES,
    ).order_by('sequence_number', 'action_code'):
        code = (row.action_code or '').strip().upper()
        if code == AUTO_COD_VERIFY_ACTION_CODE:
            continue
        impact = resolve_shipment_status_impact(row.shipment_status_impact)
        if impact == TenantShipment.ShipmentStatus.DELIVERED:
            return row
    return None


def resolve_auto_close_job_action() -> TenantOperationAction | None:
    """Resolve Action Master A10 (Job Closed) for post-Delivered auto-close logs."""
    close_action = TenantOperationAction.objects.filter(
        action_code__iexact='A10',
        status=TenantOperationAction.Status.ACTIVE,
    ).first()
    if close_action is not None:
        impact = resolve_shipment_status_impact(close_action.shipment_status_impact)
        if impact == TenantShipment.ShipmentStatus.CLOSED:
            return close_action
    for row in TenantOperationAction.objects.filter(
        status=TenantOperationAction.Status.ACTIVE,
    ).order_by('sequence_number', 'action_code'):
        code = (row.action_code or '').strip().upper()
        if code != 'A10':
            continue
        impact = resolve_shipment_status_impact(row.shipment_status_impact)
        if impact == TenantShipment.ShipmentStatus.CLOSED:
            return row
    return None


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
        if spec.action_code == AUTO_COD_VERIFY_ACTION_CODE and row.admin_only:
            errors.append(f'{spec.action_code}: must not be admin_only')

    verify = resolve_auto_cod_verify_action()
    if verify is None:
        errors.append(
            f'{AUTO_COD_VERIFY_ACTION_CODE} missing or shipment_status_impact not Delivered',
        )
    return errors


def repair_auto_cod_verify_logs(*, dry_run: bool = False) -> int:
    """
    Re-link auto_cod_verify logs to the correct verify action (fixes A6 mis-attachment).
    """
    verify_action = resolve_auto_cod_verify_action()
    if verify_action is None:
        return 0

    wrong_qs = TenantOperationActionLog.objects.filter(
        source_channel=AUTO_COD_VERIFY_CHANNEL,
    ).exclude(operation_action_id=verify_action.pk)

    count = wrong_qs.count()
    if count and not dry_run:
        wrong_qs.update(operation_action=verify_action)
    return count
