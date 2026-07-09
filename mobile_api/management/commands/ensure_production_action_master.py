"""
Ensure tenant Action Master matches production COD/Credit workflow spec.

Usage:
    python manage.py ensure_production_action_master
    python manage.py ensure_production_action_master --schema t_bb773f861f3048748c0a7f0ffbee0df6
    python manage.py ensure_production_action_master --dry-run
    python manage.py ensure_production_action_master --repair-logs
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django_tenants.utils import schema_context

from iroad_tenants.models import TenantRegistry
from iroad_tenants.operation_runtime.action_master_catalog import (
    PRODUCTION_ACTION_MASTER,
    repair_auto_cod_verify_logs,
    validate_production_action_master,
)
from tenant_workspace.models import TenantOperationAction


def _model_field_names(model) -> set[str]:
    return {field.name for field in model._meta.fields}


def _seed_actions(*, dry_run: bool) -> dict[str, int]:
    model_fields = _model_field_names(TenantOperationAction)
    counts = {'created': 0, 'updated': 0, 'unchanged': 0}

    with transaction.atomic():
        for spec in PRODUCTION_ACTION_MASTER:
            defaults = spec.defaults(model_fields)
            row = TenantOperationAction.objects.filter(
                action_code__iexact=spec.action_code,
            ).first()
            if row is None:
                counts['created'] += 1
                if not dry_run:
                    TenantOperationAction.objects.create(
                        action_code=spec.action_code,
                        **defaults,
                    )
                continue

            changed = [
                field
                for field, value in defaults.items()
                if getattr(row, field) != value
            ]
            if not changed:
                counts['unchanged'] += 1
                continue
            counts['updated'] += 1
            if not dry_run:
                for field, value in defaults.items():
                    setattr(row, field, value)
                row.save(update_fields=[*defaults.keys(), 'updated_at'])

        if dry_run:
            transaction.set_rollback(True)

    return counts


class Command(BaseCommand):
    help = 'Seed and validate production Action Master (A1–A10).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            default='t_bb773f861f3048748c0a7f0ffbee0df6',
            help='Tenant schema name',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview seed/repair without saving',
        )
        parser.add_argument(
            '--repair-logs',
            action='store_true',
            help='Clear mistaken Action Master links on backend auto POD verify logs',
        )
        parser.add_argument(
            '--skip-seed',
            action='store_true',
            help='Only validate (and optionally repair logs)',
        )

    def handle(self, *args, **options):
        schema = (options['schema'] or '').strip()
        dry_run = bool(options['dry_run'])

        if not TenantRegistry.objects.filter(schema_name=schema).exists():
            self.stderr.write(self.style.ERROR(f'Unknown tenant schema: {schema}'))
            return

        with schema_context(schema):
            if not options['skip_seed']:
                counts = _seed_actions(dry_run=dry_run)
                self.stdout.write(
                    f'Seed {"(dry-run) " if dry_run else ""}'
                    f'created={counts["created"]} updated={counts["updated"]} '
                    f'unchanged={counts["unchanged"]}',
                )

            errors = validate_production_action_master()
            if errors:
                self.stderr.write(self.style.ERROR('Action Master validation FAILED:'))
                for err in errors:
                    self.stderr.write(f'  - {err}')
            else:
                self.stdout.write(self.style.SUCCESS('Action Master validation: PASS'))

            if options['repair_logs']:
                repaired = repair_auto_cod_verify_logs(dry_run=dry_run)
                self.stdout.write(
                    f'Auto-verify log repair: {repaired} row(s) '
                    f'{"would be " if dry_run else ""}updated',
                )

        if errors:
            raise SystemExit(1)
