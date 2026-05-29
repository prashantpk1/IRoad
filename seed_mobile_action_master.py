"""Seed canonical tenant Action Master rows for the mobile job workflow.

The seed is idempotent. It updates existing canonical rows and renames the
previous 5-row mobile seed codes instead of creating duplicate workflow steps.

Usage:
    python seed_mobile_action_master.py
    python seed_mobile_action_master.py --schema t_bb773f861f3048748c0a7f0ffbee0df6
    python seed_mobile_action_master.py --dry-run
    python seed_mobile_action_master.py --check-shipment-id 8b4e09cb-91c6-4e70-81de-a5b57afee774
"""

from __future__ import annotations

import argparse
import os
DEFAULT_SCHEMA = 't_bb773f861f3048748c0a7f0ffbee0df6'

# Re-export production catalog (includes A_POD_VERIFY).
from iroad_tenants.operation_runtime.action_master_catalog import (  # noqa: E402
    PRODUCTION_ACTION_MASTER as CANONICAL_ACTIONS,
)

LEGACY_CODE_MAP = {
    'A2': ('ACT-AAAC',),
    'A3': ('ACT-AAAD',),
    'A5': ('OA-AAAE',),
    'A6': ('OA-AAAF',),
    'A7': ('OA-AAAG',),
}


def setup_django() -> None:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    debug_value = os.environ.get('DEBUG', '')
    valid_debug_values = {'1', '0', 'true', 'false', 'yes', 'no', 'on', 'off', ''}
    if debug_value.strip().lower() not in valid_debug_values:
        os.environ['DEBUG'] = 'True'
    else:
        os.environ.setdefault('DEBUG', 'True')

    import django

    django.setup()


def changed_fields(instance, defaults: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for field, value in defaults.items():
        if getattr(instance, field) != value:
            changed.append(field)
    return changed


def validate_schema(schema_name: str) -> None:
    from django_tenants.utils import schema_context
    from iroad_tenants.models import TenantRegistry

    with schema_context('public'):
        exists = TenantRegistry.objects.filter(schema_name=schema_name).exists()
    if not exists:
        raise SystemExit(f'Unknown tenant schema: {schema_name}')


def _model_field_names(model) -> set[str]:
    return {field.name for field in model._meta.fields}


def _find_existing_action(model, canonical_code: str):
    existing = model.objects.filter(action_code__iexact=canonical_code).first()
    if existing is not None:
        return existing, False
    for legacy_code in LEGACY_CODE_MAP.get(canonical_code, ()):
        existing = model.objects.filter(action_code__iexact=legacy_code).first()
        if existing is not None:
            return existing, True
    return None, False


def seed_actions(schema_name: str, *, dry_run: bool) -> dict[str, int]:
    from django.db import transaction
    from django_tenants.utils import schema_context
    from tenant_workspace.models import TenantOperationAction

    model_fields = _model_field_names(TenantOperationAction)
    counts = {'created': 0, 'updated': 0, 'renamed': 0, 'unchanged': 0}

    with schema_context(schema_name):
        with transaction.atomic():
            for action in CANONICAL_ACTIONS:
                defaults = action.defaults(model_fields)
                existing, is_legacy = _find_existing_action(
                    TenantOperationAction,
                    action.action_code,
                )

                if existing is None:
                    counts['created'] += 1
                    print(f'CREATE {action.action_code}: {action.english_label}')
                    if not dry_run:
                        TenantOperationAction.objects.create(
                            action_code=action.action_code,
                            **defaults,
                        )
                    continue

                fields = changed_fields(existing, defaults)
                if is_legacy and existing.action_code != action.action_code:
                    fields.insert(0, 'action_code')

                if not fields:
                    counts['unchanged'] += 1
                    print(f'OK     {action.action_code}: already correct')
                    continue

                if is_legacy:
                    counts['renamed'] += 1
                    print(
                        f'RENAME {existing.action_code} -> '
                        f'{action.action_code}: {action.english_label}'
                    )
                else:
                    counts['updated'] += 1
                    print(
                        f'UPDATE {action.action_code}: {action.english_label} '
                        f'({", ".join(fields)})'
                    )
                if not dry_run:
                    existing.action_code = action.action_code
                    for field, value in defaults.items():
                        setattr(existing, field, value)
                    update_fields = sorted(set([*defaults.keys(), 'action_code', 'updated_at']))
                    existing.save(update_fields=update_fields)

            if dry_run:
                transaction.set_rollback(True)

    return counts


def print_action_table(schema_name: str) -> None:
    from django_tenants.utils import schema_context
    from tenant_workspace.models import TenantOperationAction

    wanted = [action.action_code for action in CANONICAL_ACTIONS]
    with schema_context(schema_name):
        rows = {
            row.action_code.upper(): row
            for row in TenantOperationAction.objects.filter(action_code__in=wanted)
        }

    print('code | label | scope | seq | auto_posts | status_impacts')
    print('--- | --- | --- | --- | --- | ---')
    for seed in CANONICAL_ACTIONS:
        row = rows.get(seed.action_code)
        if row is None:
            print(f'{seed.action_code} | MISSING | {seed.action_scope.title()} | {seed.sequence_number} | - | -')
            continue
        auto_posts = ','.join(
            name
            for name, enabled in (
                ('shipment', getattr(row, 'auto_shipment_post', False)),
                ('movement', getattr(row, 'auto_movement_post', False)),
                ('pod', getattr(row, 'auto_pod_post', False)),
                ('treasury', getattr(row, 'auto_treasury_post', False)),
            )
            if enabled
        ) or 'none'
        impacts = ', '.join(
            value
            for value in (
                f'booking={row.booking_status_impact}' if row.booking_status_impact else '',
                f'shipment={row.shipment_status_impact}' if row.shipment_status_impact else '',
                f'movement={row.movement_status_impact}' if row.movement_status_impact else '',
            )
            if value
        ) or 'none'
        print(
            f'{row.action_code} | {row.english_label} | '
            f'{(row.action_scope or "").title()} | {row.sequence_number} | '
            f'{auto_posts} | {impacts}'
        )


def print_allowed_actions(schema_name: str, shipment_id: str) -> None:
    from django_tenants.utils import schema_context
    from iroad_tenants.operation_execution import get_allowed_actions
    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        derive_shipment_execution_stage,
        execution_stage_operational_label,
    )
    from tenant_workspace.models import TenantShipment

    with schema_context(schema_name):
        shipment = TenantShipment.objects.filter(pk=shipment_id).first()
        if shipment is None:
            print(f'SHIPMENT CHECK skipped: not found {shipment_id}')
            return

        stage = derive_shipment_execution_stage(shipment)
        allowed = list(get_allowed_actions(shipment=shipment).order_by('sequence_number'))
        print(
            'SHIPMENT CHECK '
            f'{shipment.shipment_no} status={shipment.shipment_status} '
            f'stage={execution_stage_operational_label(stage)}'
        )
        if not allowed:
            print('ALLOWED none')
            return
        for action in allowed:
            print(
                'ALLOWED '
                f'{action.sequence_number}. {action.action_code} '
                f'{action.english_label}'
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Seed canonical mobile Action Master rows for a tenant.',
    )
    parser.add_argument(
        '--schema',
        default=DEFAULT_SCHEMA,
        help=f'Tenant schema name. Default: {DEFAULT_SCHEMA}',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print changes without saving them.',
    )
    parser.add_argument(
        '--check-shipment-id',
        default='',
        help='Optional shipment UUID to print allowed actions after seeding.',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_django()
    validate_schema(args.schema)
    counts = seed_actions(args.schema, dry_run=args.dry_run)
    mode = 'DRY RUN' if args.dry_run else 'APPLIED'
    print(
        f'{mode}: created={counts["created"]} '
        f'updated={counts["updated"]} renamed={counts["renamed"]} '
        f'unchanged={counts["unchanged"]}'
    )
    print_action_table(args.schema)
    if args.check_shipment_id:
        print_allowed_actions(args.schema, args.check_shipment_id)


if __name__ == '__main__':
    main()
