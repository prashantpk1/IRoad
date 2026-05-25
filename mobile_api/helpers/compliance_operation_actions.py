"""
Resolve canonical POD (A7) and COD (A9) rows from Action Master.
"""

from __future__ import annotations

from iroad_tenants.operation_execution import action_matches
from tenant_workspace.models import TenantOperationAction

POD_ACTION_NEEDLES = ('upload pod', 'a7', 'action 7')
COD_ACTION_NEEDLES = ('collect payment', 'a9', 'action 9')


def _pick_best_action(candidates: list, *, prefer_auto_pod: bool = False) -> TenantOperationAction | None:
    if not candidates:
        return None
    if prefer_auto_pod:
        for row in candidates:
            if getattr(row, 'auto_pod_post', False):
                return row
    return sorted(candidates, key=lambda a: (a.sequence_number or 0, a.action_code or ''))[0]


def resolve_pod_upload_action() -> TenantOperationAction | None:
    rows = [
        row
        for row in TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
        ).order_by('sequence_number', 'action_code')
        if action_matches(row, *POD_ACTION_NEEDLES)
    ]
    return _pick_best_action(rows, prefer_auto_pod=True)


def resolve_cod_collect_action() -> TenantOperationAction | None:
    rows = [
        row
        for row in TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
        ).order_by('sequence_number', 'action_code')
        if action_matches(row, *COD_ACTION_NEEDLES)
    ]
    return _pick_best_action(rows)
