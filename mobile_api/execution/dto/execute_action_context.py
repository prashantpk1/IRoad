"""
mobile_api/execution/dto/execute_action_context.py

In-memory orchestration context for one execute-action request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

JobType = Literal['shipment', 'movement', 'booking']


@dataclass
class ExecuteActionContext:
    """
    Populated across the execute pipeline before ``ExecuteActionResponseBuilder``.

    Reuses the same explicit job scope as Job Detail (not dashboard current-job).
    """

    driver: Any
    tenant_schema: str
    user_id: str
    job_type: JobType
    job_id: str
    action_code: str

    # Resolved domain rows (set by job resolvers — same as job_detail)
    shipment: Any | None = None
    movement: Any | None = None
    booking: Any | None = None
    operation_action: Any | None = None

    # Normalized inbound payload (validated by serializer upstream)
    payload: dict[str, Any] = field(default_factory=dict)

    # Reconciliation + projection slices (post-execute read model)
    reconciliation: dict[str, Any] = field(default_factory=dict)
    workflow: dict[str, Any] = field(default_factory=dict)
    pod_cod: dict[str, Any] = field(default_factory=dict)
    round_trip: dict[str, Any] = field(default_factory=dict)
    timeline: dict[str, Any] = field(default_factory=dict)
    alerts: dict[str, Any] = field(default_factory=dict)
    sync_metadata: dict[str, Any] = field(default_factory=dict)
    job: dict[str, Any] = field(default_factory=dict)

    # Kernel result (``ActionExecutionResult``) — set after execute step
    action_log: Any | None = None
    reused_existing: bool = False

    projection_cache: Any | None = None
    resolver_meta: dict[str, Any] = field(default_factory=dict)

    # Authoritative pre-execute contract (resolve + reconcile + overlay + workflow)
    authoritative: dict[str, Any] = field(default_factory=dict)
    latest_action_log_id: str = ''
    content_hash: str = ''

    # Normalized idempotency (``client_action_id`` → ``idempotency_key``)
    idempotency_key: str = ''
    source_ref: str = ''

    # Set when validation detects an existing Action Log for the idempotency key
    idempotent_replay: bool = False
