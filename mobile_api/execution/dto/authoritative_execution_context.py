"""
mobile_api/execution/dto/authoritative_execution_context.py

Canonical pre-execute context returned to validation / stale guards / response builders.
"""
from __future__ import annotations

from typing import Any, TypedDict


class AuthoritativeExecutionContext(TypedDict, total=False):
    """
    Log-primary execution snapshot before kernel mutation.

    Keys:
        job_type: ``shipment`` | ``movement``
        entity: resolver identity + reconciled status fields
        workflow: Action-Master-driven stage + allowed_actions (overlay applied)
        reconciled_state: entity reconcile slice (authoritative_status, drift, …)
        allowed_actions: flattened list from workflow (convenience)
        sync_metadata: content_hash, workflow_version, entity_versions, …
    """

    job_type: str
    entity: dict[str, Any]
    workflow: dict[str, Any]
    reconciled_state: dict[str, Any]
    allowed_actions: list[dict[str, Any]]
    sync_metadata: dict[str, Any]
