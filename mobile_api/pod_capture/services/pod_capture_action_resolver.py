"""
mobile_api/pod_capture/services/pod_capture_action_resolver.py

Resolve POD Action Master row when the client omits ``target_action_code``.

Uses tenant Action Master metadata (``auto_pod_post``, POD upload needles) — not hardcoded codes.
"""
from __future__ import annotations

from typing import Any

from django_tenants.utils import schema_context

from mobile_api.pod_capture.policy.canonical_pod_action_registry import is_pod_upload_action


def resolve_default_pod_action(tenant_schema: str) -> Any | None:
    """
    First active tenant operation action eligible for POD capture.

    Returns:
        ``TenantOperationAction`` instance or ``None``.
    """
    schema = (tenant_schema or '').strip()
    if not schema:
        return None

    with schema_context(schema):
        from tenant_workspace.models import TenantOperationAction

        candidates = (
            TenantOperationAction.objects.exclude(
                status=TenantOperationAction.Status.INACTIVE,
            )
            .order_by('line_no', 'action_code')
        )
        for action in candidates:
            if is_pod_upload_action(action):
                return action
            if getattr(action, 'auto_pod_post', False):
                return action
            if getattr(action, 'hard_copy_collection', False):
                return action
    return None
