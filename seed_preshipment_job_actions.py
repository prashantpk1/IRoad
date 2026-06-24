"""Seed job Action Master OA-0001..OA-0010 (+ system A_POD_VERIFY).

Renames legacy shipment codes OA-0003..0006 → OA-0005..0008, then seeds:
  OA-0001 Start Job
  OA-0002 Pickup Arrival
  OA-0003 Start Loading
  OA-0004 Confirm Loaded  (Auto Movement + Auto Shipment ON)
  OA-0005 Shipment In Transit
  OA-0006 Delivery Arrival
  OA-0007 Start Unloading
  OA-0008 POD
  OA-0009 Collect Payment (COD)
  OA-0010 Job Closed

Also migrates legacy A1–A4 / A9–A10 rows when present.

Usage:
    python seed_preshipment_job_actions.py --dry-run
    python seed_preshipment_job_actions.py --schema t_YOUR_TENANT_SCHEMA
"""

from __future__ import annotations

import argparse
import os
from typing import Any

DEFAULT_SCHEMA = 't_d5d38bc1b3c44cd88a3d0d6eb61a7b12'

# One-time shipment-code shifts (old layout → OA-0005..0008).
# Only runs when the row at old_code still has source_label (pre-migration layout).
CODE_RENAMES: tuple[tuple[str, str, str], ...] = (
    ('OA-0006', 'OA-0008', 'POD'),
    ('OA-0005', 'OA-0007', 'Start Unloading'),
    ('OA-0004', 'OA-0006', 'Delivery Arrival'),
    ('OA-0003', 'OA-0005', 'Shipment In Transit'),
)

LEGACY_CODE_RENAMES: tuple[tuple[str, str], ...] = (
    ('A1', 'OA-0001'),
    ('A2', 'OA-0002'),
    ('A3', 'OA-0003'),
    ('A4', 'OA-0004'),
    ('A9', 'OA-0009'),
    ('A10', 'OA-0010'),
)

_TEMP_PREFIX = '__TMP__'

JOB_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        'action_code': 'OA-0001',
        'english_label': 'Start Job',
        'arabic_label': 'ابدأ العمل',
        'sequence_number': 1,
        'auto_movement_post': False,
        'auto_shipment_post': False,
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'booking_status_impact': 'In_Execution',
        'shipment_status_impact': '',
        'movement_status_impact': '',
    },
    {
        'action_code': 'OA-0002',
        'english_label': 'Pickup Arrival',
        'arabic_label': 'وصول موقع التحميل',
        'sequence_number': 2,
        'auto_movement_post': False,
        'auto_shipment_post': False,
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'booking_status_impact': '',
        'shipment_status_impact': '',
        'movement_status_impact': '',
    },
    {
        'action_code': 'OA-0003',
        'english_label': 'Start Loading',
        'arabic_label': 'بدء التحميل',
        'sequence_number': 3,
        'auto_movement_post': False,
        'auto_shipment_post': False,
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'booking_status_impact': '',
        'shipment_status_impact': '',
        'movement_status_impact': '',
    },
    {
        'action_code': 'OA-0004',
        'english_label': 'Confirm Loaded',
        'arabic_label': 'تأكيد التحميل',
        'sequence_number': 4,
        'auto_movement_post': True,
        'auto_shipment_post': True,
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'booking_status_impact': 'In_Execution',
        'shipment_status_impact': 'Loaded',
        'movement_status_impact': 'Scheduled',
    },
    {
        'action_code': 'OA-0005',
        'english_label': 'Shipment In Transit',
        'arabic_label': 'الشحنة قيد النقل',
        'sequence_number': 5,
        'auto_movement_post': False,
        'auto_shipment_post': False,
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'booking_status_impact': '',
        'shipment_status_impact': 'In_Transit',
        'movement_status_impact': '',
    },
    {
        'action_code': 'OA-0006',
        'english_label': 'Delivery Arrival',
        'arabic_label': 'الوصول لموقع التفريغ',
        'sequence_number': 6,
        'auto_movement_post': False,
        'auto_shipment_post': False,
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'booking_status_impact': '',
        'shipment_status_impact': 'At_Delivery',
        'movement_status_impact': '',
    },
    {
        'action_code': 'OA-0007',
        'english_label': 'Start Unloading',
        'arabic_label': 'بدأ التفريغ',
        'sequence_number': 7,
        'auto_movement_post': False,
        'auto_shipment_post': False,
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'booking_status_impact': '',
        'shipment_status_impact': 'At_Delivery',
        'movement_status_impact': '',
    },
    {
        'action_code': 'OA-0008',
        'english_label': 'POD',
        'arabic_label': 'تأكيد التسليم',
        'sequence_number': 8,
        'auto_movement_post': False,
        'auto_shipment_post': False,
        'auto_pod_post': True,
        'hard_copy_collection': True,
        'booking_status_impact': '',
        'shipment_status_impact': 'POD_Submitted',
        'movement_status_impact': '',
    },
    {
        'action_code': 'OA-0009',
        'english_label': 'Collect Payment',
        'arabic_label': 'تحصيل الدفع',
        'sequence_number': 9,
        'auto_movement_post': False,
        'auto_shipment_post': False,
        'auto_pod_post': False,
        'auto_treasury_post': True,
        'hard_copy_collection': False,
        'booking_status_impact': '',
        'shipment_status_impact': '',
        'movement_status_impact': '',
        'condition_code': 'Order_Type_must_be_COD',
    },
    {
        'action_code': 'OA-0010',
        'english_label': 'Job Closed',
        'arabic_label': 'إغلاق العمل',
        'sequence_number': 10,
        'auto_movement_post': False,
        'auto_shipment_post': False,
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'booking_status_impact': 'Executed',
        'shipment_status_impact': 'Closed',
        'movement_status_impact': '',
        'condition_code': 'A9_required_if_COD',
    },
    {
        'action_code': 'A_POD_VERIFY',
        'english_label': 'POD Verified',
        'arabic_label': 'تم التحقق من POD',
        'sequence_number': 75,
        'auto_movement_post': False,
        'auto_shipment_post': False,
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'mobile_visible': False,
        'admin_only': False,
        'booking_status_impact': '',
        'shipment_status_impact': 'Delivered',
        'movement_status_impact': '',
        'action_scope': 'job',
        'sequence_category': 'job',
    },
)

COMMON_DEFAULTS = {
    'status': 'Active',
    'action_scope': 'job',
    'sequence_category': 'job',
    'mobile_visible': True,
    'admin_only': False,
    'auto_treasury_post': False,
}


def setup_django() -> None:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    os.environ.setdefault('DEBUG', 'True')
    import django

    django.setup()


def _model_field_names(model) -> set[str]:
    return {field.name for field in model._meta.fields}


def validate_schema(schema_name: str) -> None:
    from django_tenants.utils import schema_context
    from iroad_tenants.models import TenantRegistry

    with schema_context('public'):
        if not TenantRegistry.objects.filter(schema_name=schema_name).exists():
            raise SystemExit(f'Unknown tenant schema: {schema_name}')


def _normalize_label(value: str) -> str:
    return (value or '').strip().casefold()


def _final_layout_ready(model) -> bool:
    """True when all OA-0001..OA-0010 exist with expected labels."""
    for spec in JOB_ACTIONS:
        row = model.objects.filter(action_code__iexact=spec['action_code']).first()
        if row is None:
            return False
        if _normalize_label(row.english_label) != _normalize_label(spec['english_label']):
            return False
    return True


def _recover_stuck_temp_codes(model, *, dry_run: bool) -> int:
    """Fix partial runs that left __TMP__ rows behind."""
    count = 0
    for spec in JOB_ACTIONS:
        code = spec['action_code']
        temp_code = f'{_TEMP_PREFIX}{code}'
        temp_row = model.objects.filter(action_code__iexact=temp_code).first()
        if temp_row is None:
            continue
        final_row = model.objects.filter(action_code__iexact=code).first()
        if final_row is not None:
            print(
                f'CLEAN  {temp_code} ({temp_row.english_label}) — '
                f'{code} already exists'
            )
            if not dry_run:
                temp_row.delete()
        else:
            print(f'RENAME {temp_code} -> {code} ({temp_row.english_label})')
            if not dry_run:
                temp_row.action_code = code
                temp_row.save(update_fields=['action_code', 'updated_at'])
        count += 1
    return count


def _migrate_codes(
    model,
    renames: tuple[tuple[str, ...], ...],
    *,
    dry_run: bool,
    via_temp: bool = False,
    require_source_label: bool = False,
) -> int:
    """Apply renames; use two-phase temp codes when targets may still be occupied."""
    count = 0
    finals: list[tuple[str, str, str]] = []

    for entry in renames:
        old_code, new_code = entry[0], entry[1]
        source_label = entry[2] if len(entry) > 2 else ''

        if old_code.upper() == new_code.upper():
            continue

        row = model.objects.filter(action_code__iexact=old_code).first()
        if row is None:
            continue

        if require_source_label and source_label:
            if _normalize_label(row.english_label) != _normalize_label(source_label):
                print(
                    f'SKIP   {old_code}: expected "{source_label}", '
                    f'found "{row.english_label}"'
                )
                continue

        label = row.english_label or ''
        target_row = model.objects.filter(action_code__iexact=new_code).first()
        if target_row is not None and target_row.pk != row.pk:
            print(f'SKIP   {old_code} -> {new_code}: target already exists')
            continue

        if via_temp or target_row is not None:
            temp_code = f'{_TEMP_PREFIX}{new_code}'
            print(f'RENAME {old_code} -> {temp_code} ({label})')
            if not dry_run:
                row.action_code = temp_code
                row.save(update_fields=['action_code', 'updated_at'])
            finals.append((temp_code, new_code, label))
        else:
            print(f'RENAME {old_code} -> {new_code} ({label})')
            if not dry_run:
                row.action_code = new_code
                row.save(update_fields=['action_code', 'updated_at'])
        count += 1

    for temp_code, new_code, label in finals:
        if model.objects.filter(action_code__iexact=new_code).exists():
            print(f'SKIP   {temp_code} -> {new_code}: target already exists')
            if not dry_run:
                temp_row = model.objects.filter(action_code__iexact=temp_code).first()
                if temp_row is not None:
                    temp_row.delete()
            continue
        print(f'RENAME {temp_code} -> {new_code} ({label})')
        if not dry_run:
            row = model.objects.filter(action_code__iexact=temp_code).first()
            if row is None:
                raise SystemExit(f'Missing temp row {temp_code} during migration')
            row.action_code = new_code
            row.save(update_fields=['action_code', 'updated_at'])

    return count


def _apply_row(model, spec: dict[str, Any], model_fields: set[str], *, dry_run: bool) -> str:
    code = spec['action_code']
    row = model.objects.filter(action_code__iexact=code).first()
    defaults = {
        **COMMON_DEFAULTS,
        **{k: v for k, v in spec.items() if k != 'action_code'},
    }
    defaults = {k: v for k, v in defaults.items() if k in model_fields}

    if row is None:
        print(f'CREATE {code}: {defaults.get("english_label", "")} seq={defaults.get("sequence_number")}')
        if not dry_run:
            model.objects.create(action_code=code, **defaults)
        return 'created'

    changed = [f for f, v in defaults.items() if getattr(row, f) != v]
    if not changed:
        print(f'OK     {code}: already correct (seq {row.sequence_number})')
        return 'unchanged'

    print(f'UPDATE {code}: {", ".join(changed)}')
    if not dry_run:
        for field, value in defaults.items():
            setattr(row, field, value)
        row.save(update_fields=[*defaults.keys(), 'updated_at'])
    return 'updated'


def _ensure_single_auto_movement(model, confirm_loaded_code: str, *, dry_run: bool) -> None:
    owner = model.objects.filter(action_code__iexact=confirm_loaded_code).first()
    if owner is None:
        return
    others = model.objects.filter(auto_movement_post=True).exclude(pk=owner.pk)
    if not others.exists():
        if not owner.auto_movement_post and not dry_run:
            owner.auto_movement_post = True
            owner.save(update_fields=['auto_movement_post', 'updated_at'])
            print(f'UPDATE {confirm_loaded_code}: auto_movement_post=True')
        return
    for row in others:
        print(f'UPDATE {row.action_code}: auto_movement_post=False')
        if not dry_run:
            row.auto_movement_post = False
            row.save(update_fields=['auto_movement_post', 'updated_at'])


def seed_preshipment(schema_name: str, *, dry_run: bool) -> dict[str, int]:
    from django.db import transaction
    from django_tenants.utils import schema_context
    from iroad_tenants.operation_action_form import repack_sequence_category
    from tenant_workspace.models import TenantOperationAction

    model_fields = _model_field_names(TenantOperationAction)
    counts = {'created': 0, 'updated': 0, 'unchanged': 0, 'renamed': 0}

    with schema_context(schema_name):
        with transaction.atomic():
            counts['renamed'] += _recover_stuck_temp_codes(
                TenantOperationAction, dry_run=dry_run,
            )

            if not _final_layout_ready(TenantOperationAction):
                counts['renamed'] += _migrate_codes(
                    TenantOperationAction,
                    CODE_RENAMES,
                    dry_run=dry_run,
                    via_temp=True,
                    require_source_label=True,
                )
                counts['renamed'] += _migrate_codes(
                    TenantOperationAction,
                    LEGACY_CODE_RENAMES,
                    dry_run=dry_run,
                )
            else:
                print('SKIP   code migration: OA-0001..OA-0010 layout already in place')

            counts['renamed'] += _migrate_codes(
                TenantOperationAction,
                (('A9', 'OA-0009'), ('A10', 'OA-0010')),
                dry_run=dry_run,
            )

            for spec in JOB_ACTIONS:
                result = _apply_row(
                    TenantOperationAction,
                    spec,
                    model_fields,
                    dry_run=dry_run,
                )
                counts[result] += 1

            _ensure_single_auto_movement(
                TenantOperationAction,
                'OA-0004',
                dry_run=dry_run,
            )

            if not dry_run:
                repack_sequence_category('job')

            if not dry_run:
                from iroad_tenants.operation_action_form import (
                    sync_operation_action_auto_number_sequence,
                )

                sync_operation_action_auto_number_sequence()

            if dry_run:
                transaction.set_rollback(True)

    return counts


def print_job_sequence_table(schema_name: str) -> None:
    from django_tenants.utils import schema_context
    from tenant_workspace.models import TenantOperationAction

    codes = [s['action_code'] for s in JOB_ACTIONS]

    with schema_context(schema_name):
        rows = list(
            TenantOperationAction.objects.filter(
                sequence_category='job',
                action_code__in=codes,
            ).order_by('sequence_number', 'action_code')
        )

    print('\nSeq | Code     | English label        | AutoMv | AutoShp | AutoPOD')
    print('----|----------|----------------------|--------|---------|--------')
    for row in rows:
        print(
            f'{row.sequence_number:3} | {row.action_code:<8} | '
            f'{(row.english_label or "")[:20]:<20} | '
            f'{"ON" if row.auto_movement_post else "OFF":6} | '
            f'{"ON" if row.auto_shipment_post else "OFF":7} | '
            f'{"ON" if row.auto_pod_post else "OFF":6}'
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Seed OA-0001..OA-0010 job workflow (preship + shipment + POD + COD).',
    )
    parser.add_argument('--schema', default=DEFAULT_SCHEMA)
    parser.add_argument('--dry-run', action='store_true')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_django()
    validate_schema(args.schema)
    counts = seed_preshipment(args.schema, dry_run=args.dry_run)
    mode = 'DRY RUN' if args.dry_run else 'APPLIED'
    print(
        f'\n{mode}: created={counts["created"]} updated={counts["updated"]} '
        f'unchanged={counts["unchanged"]} renamed={counts["renamed"]}'
    )
    print_job_sequence_table(args.schema)


if __name__ == '__main__':
    main()
