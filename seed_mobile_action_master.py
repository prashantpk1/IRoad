"""Seed tenant Action Master rows for the mobile shipment workflow.

This script is intentionally idempotent. It repairs the existing tenant rows
shown in the Operation Actions UI instead of creating duplicate action codes.

Usage:
    python seed_mobile_action_master.py
    python seed_mobile_action_master.py --schema t_bb773f861f3048748c0a7f0ffbee0df6
    python seed_mobile_action_master.py --dry-run
    python seed_mobile_action_master.py --check-shipment-id 8b4e09cb-91c6-4e70-81de-a5b57afee774
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any


DEFAULT_SCHEMA = 't_bb773f861f3048748c0a7f0ffbee0df6'


@dataclass(frozen=True)
class ActionSeed:
    action_code: str
    english_label: str
    arabic_label: str
    sequence_number: int
    auto_movement_post: bool = False
    auto_shipment_post: bool = False
    auto_pod_post: bool = False
    hard_copy_collection: bool = False
    booking_status_impact: str = ''
    shipment_status_impact: str = ''
    movement_status_impact: str = ''
    action_scope: str = 'job'
    sequence_category: str = 'job'
    status: str = 'Active'

    def defaults(self) -> dict[str, Any]:
        return {
            'english_label': self.english_label,
            'arabic_label': self.arabic_label,
            'status': self.status,
            'action_scope': self.action_scope,
            'sequence_category': self.sequence_category,
            'sequence_number': self.sequence_number,
            'auto_movement_post': self.auto_movement_post,
            'auto_shipment_post': self.auto_shipment_post,
            'auto_pod_post': self.auto_pod_post,
            'hard_copy_collection': self.hard_copy_collection,
            'booking_status_impact': self.booking_status_impact,
            'shipment_status_impact': self.shipment_status_impact,
            'movement_status_impact': self.movement_status_impact,
        }


MOBILE_SHIPMENT_ACTIONS = (
    # A2/A3 are shipment-log sequenced by the execution engine. Keep impacts
    # blank so pickup/loading are controlled by log evidence, not status jumps.
    ActionSeed(
        action_code='ACT-AAAC',
        english_label='Pickup',
        arabic_label='pickup',
        sequence_number=1,
    ),
    ActionSeed(
        action_code='ACT-AAAD',
        english_label='Start Loading',
        arabic_label='Loading',
        sequence_number=2,
    ),
    ActionSeed(
        action_code='OA-AAAE',
        english_label='In Transit',
        arabic_label='In Transit',
        sequence_number=3,
        shipment_status_impact='In Transit',
        movement_status_impact='In Progress',
        auto_movement_post=True,
    ),
    ActionSeed(
        action_code='OA-AAAF',
        english_label='Delivery',
        arabic_label='Delivery',
        sequence_number=4,
        shipment_status_impact='At Delivery',
    ),
    ActionSeed(
        action_code='OA-AAAG',
        english_label='POD',
        arabic_label='POD',
        sequence_number=5,
        shipment_status_impact='POD Submitted',
        auto_pod_post=True,
    ),
)


def setup_django() -> None:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    # Local .env files in this project have occasionally carried invalid DEBUG
    # values. This keeps the seed runnable unless the caller explicitly sets it.
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


def seed_actions(schema_name: str, *, dry_run: bool) -> dict[str, int]:
    from django.db import transaction
    from django_tenants.utils import schema_context
    from tenant_workspace.models import TenantOperationAction

    counts = {'created': 0, 'updated': 0, 'unchanged': 0}

    with schema_context(schema_name):
        with transaction.atomic():
            for action in MOBILE_SHIPMENT_ACTIONS:
                defaults = action.defaults()
                existing = TenantOperationAction.objects.filter(
                    action_code=action.action_code,
                ).first()

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
                if not fields:
                    counts['unchanged'] += 1
                    print(f'OK     {action.action_code}: already correct')
                    continue

                counts['updated'] += 1
                print(
                    f'UPDATE {action.action_code}: {action.english_label} '
                    f'({", ".join(fields)})'
                )
                if not dry_run:
                    for field, value in defaults.items():
                        setattr(existing, field, value)
                    existing.save(update_fields=[*defaults.keys(), 'updated_at'])

            if dry_run:
                transaction.set_rollback(True)

    return counts


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
        description='Seed mobile shipment Action Master rows for a tenant.',
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
        f'updated={counts["updated"]} unchanged={counts["unchanged"]}'
    )
    if args.check_shipment_id:
        print_allowed_actions(args.schema, args.check_shipment_id)


if __name__ == '__main__':
    main()
