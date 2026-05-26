"""
mobile_api/job_detail/dto/job_detail_context.py

In-memory orchestration context for a single explicit job (not API output).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

JobType = Literal['shipment', 'movement']


@dataclass
class JobDetailContext:
    """
    Populated by ``JobDetailContextService.resolve_job_detail_context``.

    Holds resolved entities, reconciliation bundles, and projection slices
    before ``JobDetailResponseBuilder`` maps to the outward API contract.
    """

    driver: Any
    tenant_schema: str
    user_id: str
    job_type: JobType
    job_id: str

    # Resolved domain rows (exactly one primary entity is set per job_type)
    shipment: Any | None = None
    movement: Any | None = None
    booking: Any | None = None

    # Resolver metadata (ownership, display ids, errors surfaced upstream)
    resolver_meta: dict[str, Any] = field(default_factory=dict)

    # Read-only reconciliation (workflow + compliance — populated later)
    reconciliation: dict[str, Any] = field(default_factory=dict)

    # Projection slices (populated by JobDetailProjectionService)
    job_header: dict[str, Any] = field(default_factory=dict)
    workflow: dict[str, Any] = field(default_factory=dict)
    timeline: dict[str, Any] = field(default_factory=dict)
    pod_cod: dict[str, Any] = field(default_factory=dict)
    round_trip: dict[str, Any] = field(default_factory=dict)
    alerts: dict[str, Any] = field(default_factory=dict)
    sync_metadata: dict[str, Any] = field(default_factory=dict)

    # Per-request bounded log cache (populated later — not dashboard cache)
    projection_cache: Any | None = None

    # Latest Action Log head (from projection cache)
    latest_action_log_id: str = ''

    # Polling / offline sync (populated later)
    content_hash: str = ''
    job_etag: str = ''
    poll_not_modified: bool = False
