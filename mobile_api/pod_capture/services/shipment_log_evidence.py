"""Read-only Action Log evidence flags for POD / Hard POD mobile views."""
from __future__ import annotations

from typing import Any

from django_tenants.utils import schema_context

from iroad_tenants.operation_runtime.latest_action_aggregator import (
    scoped_shipment_action_logs,
)
from mobile_api.dashboard.services.dashboard_pod_cod_reconciler import (
    _log_evidence_flags,
)
from mobile_api.job_detail.guards.ownership import driver_pk

JOB_DETAIL_ACTION_LOG_SCAN_LIMIT = 200


def resolve_shipment_log_evidence(
    shipment: Any | None,
    *,
    driver: Any | None = None,
    tenant_schema: str = '',
) -> dict[str, bool]:
    if shipment is None:
        return {}
    schema = (tenant_schema or '').strip()
    driver_id = driver_pk(driver)
    if not schema or driver_id is None:
        return {}
    try:
        with schema_context(schema):
            logs = list(
                scoped_shipment_action_logs(
                    shipment,
                    movement=None,
                    driver_id=driver_id,
                    scan_limit=JOB_DETAIL_ACTION_LOG_SCAN_LIMIT,
                ),
            )
        return dict(_log_evidence_flags(logs))
    except Exception:
        return {}
