"""
mobile_api/helpers/job_list_readiness.py

Shared tenant migration + index audit for job-list go-live.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from django.db import connection

TENANT_MIGRATIONS = (
    ('tenant_workspace', '0088_job_list_search_indexes'),
    ('tenant_workspace', '0089_job_list_movement_action_log_index'),
    ('tenant_workspace', '0090_shipment_mobile_operational_rank'),
)

TENANT_INDEXES = (
    'tenant_ship_drv_no_idx',
    'tenant_tml_drv_mno_idx',
    'tenant_tml_drv_src_idx',
    'tenant_oal_move_drv_date_idx',
    'tenant_ship_drv_rank_upd_idx',
)


@dataclass
class SchemaReadinessReport:
    schema: str
    migration_ok: dict[str, bool] = field(default_factory=dict)
    index_ok: dict[str, bool] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return all(self.migration_ok.values()) and all(self.index_ok.values())

    @property
    def issue_count(self) -> int:
        return sum(1 for v in self.migration_ok.values() if not v) + sum(
            1 for v in self.index_ok.values() if not v
        )


def list_tenant_schemas(*, explicit: Iterable[str] | None = None) -> list[str]:
    if explicit:
        return list(explicit)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name NOT IN ('public', 'pg_catalog', 'information_schema')
              AND schema_name NOT LIKE 'pg_%'
            ORDER BY schema_name
            """
        )
        return [row[0] for row in cursor.fetchall()]


def migration_applied(cursor, app: str, name: str, schema: str) -> bool:
    if schema == 'public':
        cursor.execute(
            'SELECT 1 FROM django_migrations WHERE app = %s AND name = %s LIMIT 1',
            [app, name],
        )
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


def index_exists(cursor, schema: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM pg_indexes
        WHERE schemaname = %s AND indexname = %s
        LIMIT 1
        """,
        [schema, index_name],
    )
    return cursor.fetchone() is not None


def audit_schema(cursor, schema: str) -> SchemaReadinessReport:
    report = SchemaReadinessReport(schema=schema)
    for app, name in TENANT_MIGRATIONS:
        key = f'{app}.{name}'
        report.migration_ok[key] = migration_applied(cursor, app, name, schema)
    for idx in TENANT_INDEXES:
        report.index_ok[idx] = index_exists(cursor, schema, idx)
    return report


def audit_all_schemas(*, schemas: Iterable[str] | None = None) -> list[SchemaReadinessReport]:
    names = list_tenant_schemas(explicit=schemas)
    reports: list[SchemaReadinessReport] = []
    with connection.cursor() as cursor:
        for schema in names:
            reports.append(audit_schema(cursor, schema))
    return reports


def total_issues(reports: list[SchemaReadinessReport]) -> int:
    return sum(r.issue_count for r in reports)


def any_schema_ready(reports: list[SchemaReadinessReport]) -> bool:
    return any(r.ready for r in reports)
