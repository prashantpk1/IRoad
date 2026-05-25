"""
Verify Job Detail migrations (0093–0095) and PostgreSQL indexes across tenant schemas.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from mobile_api.helpers.job_detail_readiness import (
    JOB_DETAIL_EXECUTION_INDEXES,
    JOB_DETAIL_MIGRATIONS,
    JOB_DETAIL_TIMELINE_INDEXES,
    audit_job_detail_schemas,
    run_middleware_smoke,
    total_job_detail_issues,
)


class Command(BaseCommand):
    help = (
        'Audit Job Detail timeline + execution indexes and required migrations. '
        'Exits non-zero when any tenant schema is NOT READY (go-live gate).'
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
        parser.add_argument(
            '--skip-middleware',
            action='store_true',
            help='Only audit DB migrations and indexes.',
        )

    def handle(self, *args, **options):
        schemas = options.get('schemas') or None
        reports = audit_job_detail_schemas(schemas=schemas)
        mw_ok, mw_err = True, ''
        if not options.get('skip_middleware'):
            mw_ok, mw_err = run_middleware_smoke()
            if not mw_ok:
                for report in reports:
                    report.middleware_ok = False
                    report.middleware_error = mw_err

        issues = total_job_detail_issues(reports)
        if not mw_ok:
            issues += 1

        for report in reports:
            self.stdout.write(f'--- {report.schema} ---')
            for key, ok in report.migration_ok.items():
                self.stdout.write(f'  migration {key}: {"OK" if ok else "MISSING"}')
            for idx, ok in report.timeline_index_ok.items():
                self.stdout.write(
                    f'  timeline index {idx}: {"OK" if ok else "MISSING"}'
                )
            for idx, ok in report.execution_index_ok.items():
                self.stdout.write(
                    f'  execution index {idx}: {"OK" if ok else "MISSING"}'
                )
            if report.ready:
                self.stdout.write(self.style.SUCCESS(f'  schema {report.schema}: READY'))
            else:
                self.stdout.write(self.style.WARNING(f'  schema {report.schema}: NOT READY'))

        if not mw_ok:
            self.stdout.write(self.style.ERROR(f'middleware smoke: {mw_err}'))

        if options.get('json'):
            import json

            payload = {
                'migrations': [f'{a}.{n}' for a, n in JOB_DETAIL_MIGRATIONS],
                'timeline_indexes': list(JOB_DETAIL_TIMELINE_INDEXES),
                'execution_indexes': list(JOB_DETAIL_EXECUTION_INDEXES),
                'middleware_ok': mw_ok,
                'middleware_error': mw_err,
                'schemas': [r.to_dict() for r in reports],
                'total_issues': issues,
            }
            self.stdout.write(json.dumps(payload, indent=2))

        if issues:
            self.stderr.write(
                self.style.ERROR(
                    f'{issues} Job Detail readiness issue(s). '
                    'Run: python manage.py migrate_job_detail_tenants --apply'
                )
            )
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS('Job Detail readiness OK.'))
