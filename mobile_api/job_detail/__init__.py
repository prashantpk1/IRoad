"""
mobile_api/job_detail

Unified Driver Job Detail API — explicit job execution context (shipment or empty move).

Distinct from ``mobile_api.dashboard``:
  - Dashboard selects the driver's *current* operational focus.
  - Job Detail resolves a *specific* job by ``job_type`` + ``job_id`` for the execution screen.

Orchestration entry: ``JobDetailContextService.resolve_job_detail_context``.
"""

from mobile_api.job_detail.services.job_detail_context_service import (
    JobDetailContextService,
)

__all__ = [
    'JobDetailContextService',
]
