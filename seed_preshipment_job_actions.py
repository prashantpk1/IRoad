"""Seed preshipment Action Master rows (seq 1–4) and renumber OA-0003..0006 to 5–8.

Idempotent for tenant schema. Creates/updates:
  1 Start Job
  2 Pickup Arrival
  3 Start Loading
  4 Confirm Loaded  (Auto Movement + Auto Shipment ON)

Keeps existing shipment-phase codes OA-0003..OA-0006 at sequences 5–8.

Usage:
    python seed_preshipment_job_actions.py
    python seed_preshipment_job_actions.py --schema t_YOUR_TENANT_SCHEMA
    python seed_preshipment_job_actions.py --dry-run
"""

from __future__ import annotations

import argparse
import os
from typing import Any

DEFAULT_SCHEMA = 't_d5d38bc1b3c44cd88a3d0d6eb61a7b12'

PRESHIPMENT_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        'action_code': 'A1',
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
        'action_code': 'A2',
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
        'action_code': 'A3',
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
        'action_code': 'A4',
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
)

# Existing tenant shipment-phase rows — sequence + safe flags only.
SHIPMENT_PHASE_RENUMBER: tuple[dict[str, Any], ...] = (
    {
        'action_code': 'OA-0003',
        'sequence_number': 5,
        'auto_movement_post': False,
        'auto_shipment_post': False,
    },
    {
        'action_code': 'OA-0004',
        'sequence_number': 6,
        'auto_movement_post': False,
        'auto_shipment_post': False,
    },
    {
        'action_code': 'OA-0005',
        'sequence_number': 7,
        'auto_movement_post': False,
        'auto_shipment_post': False,
    },
    {
        'action_code': 'OA-0006',
        'sequence_number': 8,
        # Preserve POD flags if already set in portal; do not force-off.
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


def _ensure_single_auto_movement(model, *, dry_run: bool) -> None:
    """PCS: exactly one Auto Movement Post — keep A4 only in job category."""
    from tenant_workspace.models import TenantOperationAction

    a4 = model.objects.filter(action_code__iexact='A4').first()
    if a4 is None:
        return
    others = model.objects.filter(
        sequence_category='job',
        auto_movement_post=True,
    ).exclude(pk=a4.pk)
    if not others.exists():
        if not a4.auto_movement_post and not dry_run:
            a4.auto_movement_post = True
            a4.save(update_fields=['auto_movement_post', 'updated_at'])
            print('UPDATE A4: auto_movement_post=True (required singleton)')
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
    counts = {'created': 0, 'updated': 0, 'unchanged': 0, 'missing': 0}

    with schema_context(schema_name):
        with transaction.atomic():
            # 1) Bump OA shipment rows to 5–8 first (frees 1–4).
            for spec in SHIPMENT_PHASE_RENUMBER:
                code = spec['action_code']
                row = TenantOperationAction.objects.filter(action_code__iexact=code).first()
                if row is None:
                    counts['missing'] += 1
                    print(f'MISSING {code}: create manually in portal or run full production seed')
                    continue
                patch = {k: v for k, v in spec.items() if k != 'action_code'}
                patch = {k: v for k, v in patch.items() if k in model_fields}
                changed = [f for f, v in patch.items() if getattr(row, f) != v]
                if changed:
                    print(f'UPDATE {code}: {", ".join(changed)}')
                    counts['updated'] += 1
                    if not dry_run:
                        for field, value in patch.items():
                            setattr(row, field, value)
                        row.save(update_fields=[*patch.keys(), 'updated_at'])
                else:
                    counts['unchanged'] += 1

            # 2) Preshipment A1–A4 at 1–4.
            for spec in PRESHIPMENT_ACTIONS:
                result = _apply_row(
                    TenantOperationAction,
                    spec,
                    model_fields,
                    dry_run=dry_run,
                )
                counts[result] += 1

            _ensure_single_auto_movement(TenantOperationAction, dry_run=dry_run)

            if not dry_run:
                repack_sequence_category('job')

            if dry_run:
                transaction.set_rollback(True)

    return counts


def print_job_sequence_table(schema_name: str) -> None:
    from django_tenants.utils import schema_context
    from tenant_workspace.models import TenantOperationAction

    codes = [s['action_code'] for s in PRESHIPMENT_ACTIONS]
    codes += [s['action_code'] for s in SHIPMENT_PHASE_RENUMBER]

    with schema_context(schema_name):
        rows = list(
            TenantOperationAction.objects.filter(
                sequence_category='job',
                action_code__in=codes,
            ).order_by('sequence_number', 'action_code')
        )

    print('\nSeq | Code     | English label        | AutoMv | AutoShp')
    print('----|----------|----------------------|--------|--------')
    for row in rows:
        print(
            f'{row.sequence_number:3} | {row.action_code:<8} | '
            f'{(row.english_label or "")[:20]:<20} | '
            f'{"ON" if row.auto_movement_post else "OFF":6} | '
            f'{"ON" if row.auto_shipment_post else "OFF":6}'
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Seed preshipment actions A1–A4 (seq 1–4) and renumber OA-0003..0006.',
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
        f'unchanged={counts["unchanged"]} missing_OA={counts["missing"]}'
    )
    print_job_sequence_table(args.schema)


if __name__ == '__main__':
    main()
