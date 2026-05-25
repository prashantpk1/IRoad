"""
Verify job-list migrations (0088–0090) and PostgreSQL indexes across tenant schemas.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from mobile_api.helpers.job_list_readiness import (
    TENANT_INDEXES,
    TENANT_MIGRATIONS,
    audit_all_schemas,
    total_issues,
)


class Command(BaseCommand):
    help = (
        'Audit job-list migrations and composite indexes. '
        'Exits non-zero when any issue is found (go-live gate).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            action='append',
            dest='schemas',
            help='Tenant schema to audit (repeatable). Defaults to all non-public schemas.',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Machine-readable summary on stdout.',
        )

    def handle(self, *args, **options):
        schemas = options.get('schemas') or None
        reports = audit_all_schemas(schemas=schemas)
        issues = 0
        for report in reports:
            self.stdout.write(f'--- {report.schema} ---')
            for key, ok in report.migration_ok.items():
                status = 'OK' if ok else 'MISSING'
                self.stdout.write(f'  migration {key}: {status}')
                if not ok:
                    issues += 1
            for idx, ok in report.index_ok.items():
                status = 'OK' if ok else 'MISSING'
                self.stdout.write(f'  index {idx}: {status}')
                if not ok:
                    issues += 1
            if report.ready:
                self.stdout.write(self.style.SUCCESS(f'  schema {report.schema}: READY'))
            else:
                self.stdout.write(self.style.WARNING(f'  schema {report.schema}: NOT READY'))

        if options.get('json'):
            import json

            payload = {
                'migrations': [f'{a}.{n}' for a, n in TENANT_MIGRATIONS],
                'indexes': list(TENANT_INDEXES),
                'schemas': [
                    {
                        'schema': r.schema,
                        'ready': r.ready,
                        'issues': r.issue_count,
                    }
                    for r in reports
                ],
                'total_issues': total_issues(reports),
            }
            self.stdout.write(json.dumps(payload, indent=2))

        if issues:
            self.stderr.write(
                self.style.ERROR(
                    f'{issues} readiness issue(s) found. '
                    'Run: python manage.py migrate_job_list_tenants --apply'
                )
            )
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS('Job list readiness OK.'))
