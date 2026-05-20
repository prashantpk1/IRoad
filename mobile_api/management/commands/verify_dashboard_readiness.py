"""
Verify dashboard migrations and PostgreSQL indexes across tenant + public schemas.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection

TENANT_MIGRATIONS = (
    ('tenant_workspace', '0083_dashboard_driver_counter_indexes'),
    ('tenant_workspace', '0084_current_job_action_log_index'),
    ('tenant_workspace', '0085_driver_mobile_notification'),
    ('tenant_workspace', '0086_dashboard_activity_query_indexes'),
)

PUBLIC_MIGRATIONS = (
    ('superadmin', '0038_push_dashboard_lookup_indexes'),
)

TENANT_INDEXES = (
    'tenant_book_assign_drv_idx',
    'tenant_ship_driver_status_idx',
    'tenant_oal_ship_drv_date_idx',
    'tenant_oal_driver_date_idx',
    'tenant_tml_driver_upd_idx',
    'tenant_ship_drv_stat_upd_idx',
)

PUBLIC_INDEXES = (
    'comm_push_token_drv_lookup_idx',
    'comm_push_rcpt_drv_lookup_idx',
)


def _migration_applied(cursor, app: str, name: str, schema: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM django_migrations
        WHERE app = %s AND name = %s
        LIMIT 1
        """,
        [app, name],
    )
    if schema == 'public':
        return cursor.fetchone() is not None
    cursor.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = %s AND table_name = 'django_migrations'
        """,
        [schema],
    )
    if cursor.fetchone() is None:
        return False
    cursor.execute(
        f'SELECT 1 FROM "{schema}".django_migrations WHERE app = %s AND name = %s LIMIT 1',
        [app, name],
    )
    return cursor.fetchone() is not None


def _index_exists(cursor, schema: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM pg_indexes
        WHERE schemaname = %s AND indexname = %s
        LIMIT 1
        """,
        [schema, index_name],
    )
    return cursor.fetchone() is not None


class Command(BaseCommand):
    help = (
        'Audit dashboard migrations (0083–0086 tenant, 0038 public) and '
        'composite index presence before go-live.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            dest='schema',
            default='',
            help='Single tenant schema to check (default: all TenantProfile workspace schemas).',
        )
        parser.add_argument(
            '--skip-indexes',
            action='store_true',
            help='Only verify django_migrations rows, not pg_indexes.',
        )

    def handle(self, *args, **options):
        from superadmin.models import TenantProfile

        single = (options.get('schema') or '').strip()
        schemas: list[str] = []
        if single:
            schemas = [single]
        else:
            schemas = [
                str(t.workspace_schema).strip()
                for t in TenantProfile.objects.exclude(workspace_schema='').iterator()
                if str(t.workspace_schema or '').strip()
            ]

        failures = 0
        with connection.cursor() as cursor:
            self.stdout.write('Public schema')
            for app, name in PUBLIC_MIGRATIONS:
                if not _migration_applied(cursor, app, name, 'public'):
                    failures += 1
                    self.stdout.write(self.style.ERROR(f'  MISSING migration {app}.{name}'))
                else:
                    self.stdout.write(self.style.SUCCESS(f'  OK migration {app}.{name}'))
            if not options['skip_indexes']:
                for idx in PUBLIC_INDEXES:
                    if not _index_exists(cursor, 'public', idx):
                        failures += 1
                        self.stdout.write(self.style.ERROR(f'  MISSING index {idx}'))
                    else:
                        self.stdout.write(self.style.SUCCESS(f'  OK index {idx}'))

            for schema in schemas:
                self.stdout.write(f'Tenant schema: {schema}')
                for app, name in TENANT_MIGRATIONS:
                    if not _migration_applied(cursor, app, name, schema):
                        failures += 1
                        self.stdout.write(
                            self.style.ERROR(f'  MISSING migration {app}.{name}')
                        )
                    else:
                        self.stdout.write(
                            self.style.SUCCESS(f'  OK migration {app}.{name}')
                        )
                if not options['skip_indexes']:
                    for idx in TENANT_INDEXES:
                        if not _index_exists(cursor, schema, idx):
                            failures += 1
                            self.stdout.write(self.style.ERROR(f'  MISSING index {idx}'))
                        else:
                            self.stdout.write(self.style.SUCCESS(f'  OK index {idx}'))

        if failures:
            self.stdout.write(self.style.ERROR(f'Dashboard readiness: {failures} issue(s)'))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS('Dashboard readiness: OK'))
