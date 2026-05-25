"""
Apply job-list tenant migrations (0088–0090) across tenant schemas.
"""
from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection

from mobile_api.helpers.job_list_readiness import (
    audit_all_schemas,
    list_tenant_schemas,
    total_issues,
)


class Command(BaseCommand):
    help = (
        'Run migrate_schemas for tenant_workspace on one or all tenant schemas, '
        'then verify job-list indexes.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            action='append',
            dest='schemas',
            help='Tenant schema name (repeatable). Default: all tenant schemas.',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Execute migrate_schemas (otherwise audit-only).',
        )
        parser.add_argument(
            '--backfill-rank',
            action='store_true',
            help='After migrate, backfill mobile_operational_rank on shipments.',
        )

    def handle(self, *args, **options):
        schemas = list_tenant_schemas(explicit=options.get('schemas'))
        if not schemas:
            self.stderr.write(self.style.ERROR('No tenant schemas found.'))
            raise SystemExit(1)

        if options.get('apply'):
            for schema in schemas:
                self.stdout.write(f'Migrating {schema}...')
                try:
                    call_command(
                        'migrate_schemas',
                        tenant=True,
                        schema_name=schema,
                        interactive=False,
                        verbosity=1,
                    )
                except Exception as exc:
                    self.stderr.write(self.style.ERROR(f'Failed {schema}: {exc}'))
                    raise SystemExit(1) from exc

            if options.get('backfill_rank'):
                self._backfill_operational_rank(schemas)

        reports = audit_all_schemas(schemas=schemas)
        issues = total_issues(reports)
        for report in reports:
            status = 'READY' if report.ready else 'NOT READY'
            self.stdout.write(f'{report.schema}: {status} ({report.issue_count} issues)')

        if issues:
            self.stderr.write(self.style.ERROR(f'{issues} issue(s) remain after migrate.'))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS('Job list tenant migrations OK.'))

    def _backfill_operational_rank(self, schemas: list[str]) -> None:
        from django_tenants.utils import schema_context

        from mobile_api.helpers.job_list_operational_rank import (
            apply_operational_rank_on_save,
            compute_shipment_operational_rank,
        )
        from tenant_workspace.models import TenantShipment

        for schema in schemas:
            self.stdout.write(f'Backfilling mobile_operational_rank on {schema}...')
            with schema_context(schema):
                qs = TenantShipment.objects.all().only(
                    'shipment_id',
                    'shipment_status',
                    'pod_status',
                    'collection_status',
                    'order_type',
                    'cod_amount',
                    'mobile_operational_rank',
                )
                batch: list[TenantShipment] = []
                for row in qs.iterator(chunk_size=500):
                    rank = compute_shipment_operational_rank(row)
                    if row.mobile_operational_rank != rank:
                        row.mobile_operational_rank = rank
                        batch.append(row)
                    if len(batch) >= 500:
                        TenantShipment.objects.bulk_update(
                            batch,
                            ['mobile_operational_rank'],
                        )
                        batch = []
                if batch:
                    TenantShipment.objects.bulk_update(
                        batch,
                        ['mobile_operational_rank'],
                    )
