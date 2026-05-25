"""
Job Detail module — tenant migration + PostgreSQL index readiness audits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from mobile_api.helpers.job_list_readiness import (
    index_exists,
    list_tenant_schemas,
    migration_applied,
)

# Migrations required for timeline cursor indexes (0093 adds; 0095 ensures idempotent).
JOB_DETAIL_MIGRATIONS = (
    ('tenant_workspace', '0093_job_detail_timeline_cursor_indexes'),
    (
        'tenant_workspace',
        '0095_job_detail_timeline_indexes_ensure',
    ),
)

# Cursor / timeline pagination (0093 + 0095).
JOB_DETAIL_TIMELINE_INDEXES = (
    'tenant_oal_ship_drv_dt_id_idx',
    'tenant_oal_move_drv_dt_id_idx',
    'tenant_oal_ship_created_idx',
    'tenant_oal_move_created_idx',
)

# Execution + idempotency helpers (0081, 0084, 0089).
JOB_DETAIL_EXECUTION_INDEXES = (
    'tenant_oal_ship_drv_date_idx',
    'tenant_oal_move_drv_date_idx',
    'tenant_oal_channel_idx',
    'tenant_oal_source_ref_idx',
)

JOB_DETAIL_REQUIRED_INDEXES = JOB_DETAIL_TIMELINE_INDEXES + JOB_DETAIL_EXECUTION_INDEXES


@dataclass
class JobDetailSchemaReport:
    schema: str
    migration_ok: dict[str, bool] = field(default_factory=dict)
    timeline_index_ok: dict[str, bool] = field(default_factory=dict)
    execution_index_ok: dict[str, bool] = field(default_factory=dict)
    middleware_ok: bool = True
    middleware_error: str = ''

    @property
    def missing_migrations(self) -> list[str]:
        return [k for k, ok in self.migration_ok.items() if not ok]

    @property
    def missing_timeline_indexes(self) -> list[str]:
        return [k for k, ok in self.timeline_index_ok.items() if not ok]

    @property
    def missing_execution_indexes(self) -> list[str]:
        return [k for k, ok in self.execution_index_ok.items() if not ok]

    @property
    def missing_indexes(self) -> list[str]:
        return self.missing_timeline_indexes + self.missing_execution_indexes

    @property
    def ready(self) -> bool:
        return (
            self.middleware_ok
            and not self.missing_migrations
            and not self.missing_indexes
        )

    @property
    def issue_count(self) -> int:
        n = len(self.missing_migrations) + len(self.missing_indexes)
        if not self.middleware_ok:
            n += 1
        return n

    def to_dict(self) -> dict:
        return {
            'schema': self.schema,
            'ready': self.ready,
            'issue_count': self.issue_count,
            'missing_migrations': self.missing_migrations,
            'missing_timeline_indexes': self.missing_timeline_indexes,
            'missing_execution_indexes': self.missing_execution_indexes,
            'middleware_ok': self.middleware_ok,
            'middleware_error': self.middleware_error,
        }


def audit_job_detail_schema(cursor, schema: str) -> JobDetailSchemaReport:
    report = JobDetailSchemaReport(schema=schema)
    for app, name in JOB_DETAIL_MIGRATIONS:
        key = f'{app}.{name}'
        report.migration_ok[key] = migration_applied(cursor, app, name, schema)
    for idx in JOB_DETAIL_TIMELINE_INDEXES:
        report.timeline_index_ok[idx] = index_exists(cursor, schema, idx)
    for idx in JOB_DETAIL_EXECUTION_INDEXES:
        report.execution_index_ok[idx] = index_exists(cursor, schema, idx)
    return report


def audit_job_detail_schemas(
    *,
    schemas: Iterable[str] | None = None,
) -> list[JobDetailSchemaReport]:
    names = list_tenant_schemas(explicit=schemas)
    reports: list[JobDetailSchemaReport] = []
    from django.db import connection

    with connection.cursor() as cursor:
        for schema in names:
            reports.append(audit_job_detail_schema(cursor, schema))
    return reports


def total_job_detail_issues(reports: list[JobDetailSchemaReport]) -> int:
    return sum(r.issue_count for r in reports)


def any_job_detail_ready(reports: list[JobDetailSchemaReport]) -> bool:
    return any(r.ready for r in reports)


def run_middleware_smoke() -> tuple[bool, str]:
    """
    Validate jobs middleware + Job Detail metrics on fully simulated requests.

    Covers GET timeline/detail/actions, POST execute/POD, and legacy partial fakes
    missing ``request.method`` (must not emit ``metrics_error``).
    """
    from mobile_api.helpers.middleware_request_sim import (
        build_jobs_smoke_request,
        build_minimal_legacy_fake_request,
        run_middleware_smoke_suite,
        validate_metrics_readiness_on_request,
    )

    try:
        ok, err = run_middleware_smoke_suite()
        if not ok:
            return False, err

        legacy = build_minimal_legacy_fake_request(
            '/api/v1/mobile/driver/jobs/shipments/x/timeline/',
        )
        metrics_ok, metrics_err = validate_metrics_readiness_on_request(legacy)
        if not metrics_ok:
            return False, f'metrics_readiness: {metrics_err}'

        probe = build_jobs_smoke_request(
            path='/api/v1/mobile/driver/jobs/shipments/x/timeline/',
            method='GET',
        )
        metrics_ok, metrics_err = validate_metrics_readiness_on_request(probe)
        if not metrics_ok:
            return False, f'metrics_readiness: {metrics_err}'

        return True, ''
    except Exception as exc:
        return False, str(exc)
