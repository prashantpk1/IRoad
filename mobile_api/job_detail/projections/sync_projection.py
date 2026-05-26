"""
mobile_api/job_detail/projections/sync_projection.py

``sync_metadata`` section — offline-safe fingerprints, entity versions, integrity flags.
"""
from __future__ import annotations

from typing import Any

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.services.job_detail_sync_metadata import (
    build_job_detail_sync_metadata,
)


def build_sync_metadata(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Build per-job sync metadata.

  When ``finalize_job_detail_sync`` already ran, returns the cached slice;
  otherwise builds from current projection state (tests / partial flows).
    """
    _ = request
    if context.sync_metadata:
        return dict(context.sync_metadata)
    return build_job_detail_sync_metadata(context)
