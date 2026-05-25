"""
Apply Job Detail tenant migrations (0093–0095) across tenant schemas safely.
"""
from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand

from mobile_api.helpers.job_detail_readiness import (
    audit_job_detail_schemas,
    total_job_detail_issues,
)
from mobile_api.helpers.job_list_readiness import list_tenant_schemas


class Command(BaseCommand):
    help = (
        'Run migrate_schemas per tenant for Job Detail timeline indexes (0093–0095), '
        'then audit migrations and PostgreSQL indexes. Use --apply to migrate; '
        'default is audit-only.'
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
            help='Execute migrate_schemas on each tenant (safe, sequential).',
        )
        parser.add_argument(
            '--stop-on-error',
            action='store_true',
            default=True,
            help='Stop on first tenant migrate failure (default: true).',
        )
        parser.add_argument(
            '--continue-on-error',
            action='store_true',
            help='Log failures and continue with remaining tenants.',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Emit machine-readable audit after migrate/audit.',
        )

    def handle(self, *args, **options):
        schemas = list_tenant_schemas(explicit=options.get('schemas'))
        if not schemas:
            self.stderr.write(self.style.ERROR('No tenant schemas found.'))
            raise SystemExit(1)

        stop_on_error = options.get('stop_on_error') and not options.get(
            'continue_on_error'
        )
        failures: list[str] = []

        if options.get('apply'):
            self.stdout.write(
                self.style.NOTICE(
                    f'Applying tenant_workspace migrations on {len(schemas)} schema(s)...'
                )
            )
            for schema in schemas:
                self.stdout.write(f'  -> migrate_schemas tenant={schema}')
                try:
                    call_command(
                        'migrate_schemas',
                        tenant=True,
                        schema_name=schema,
                        interactive=False,
                        verbosity=1,
                    )
                except Exception as exc:
                    failures.append(schema)
                    self.stderr.write(self.style.ERROR(f'    FAILED {schema}: {exc}'))
                    if stop_on_error:
                        raise SystemExit(1) from exc

            if failures and not stop_on_error:
                self.stderr.write(
                    self.style.WARNING(
                        f'{len(failures)} tenant(s) failed migrate: {", ".join(failures)}'
                    )
                )

        reports = audit_job_detail_schemas(schemas=schemas)
        issues = total_job_detail_issues(reports)

        if options.get('json'):
            import json

            from mobile_api.helpers.job_detail_readiness import (
                JOB_DETAIL_MIGRATIONS,
                JOB_DETAIL_REQUIRED_INDEXES,
                run_middleware_smoke,
            )

            mw_ok, mw_err = run_middleware_smoke()
            payload = {
                'migrations': [f'{a}.{n}' for a, n in JOB_DETAIL_MIGRATIONS],
                'indexes': list(JOB_DETAIL_REQUIRED_INDEXES),
                'middleware_ok': mw_ok,
                'middleware_error': mw_err,
                'migrate_failures': failures,
                'schemas': [r.to_dict() for r in reports],
                'total_issues': issues,
            }
            self.stdout.write(json.dumps(payload, indent=2))
        else:
            for report in reports:
                status = 'READY' if report.ready else 'NOT READY'
                self.stdout.write(
                    f'{report.schema}: {status} ({report.issue_count} issue(s))'
                )
                for key in report.missing_migrations:
                    self.stdout.write(f'  missing migration: {key}')
                for idx in report.missing_timeline_indexes:
                    self.stdout.write(f'  missing timeline index: {idx}')
                for idx in report.missing_execution_indexes:
                    self.stdout.write(f'  missing execution index: {idx}')

        if issues or failures:
            self.stderr.write(
                self.style.ERROR(
                    f'{issues} readiness issue(s); {len(failures)} migrate failure(s). '
                    'Run: python manage.py migrate_job_detail_tenants --apply'
                )
            )
            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(
                f'Job Detail tenant migrations and indexes OK ({len(schemas)} schema(s)).'
            )
        )
