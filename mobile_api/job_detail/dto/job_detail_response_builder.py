"""
mobile_api/job_detail/dto/job_detail_response_builder.py

Maps ``JobDetailContext`` → unified Job Detail API ``data`` contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext

_EMPTY_JOB: dict[str, Any] = {
    'job_type': '',
    'job_id': '',
    'job_no': '',
    'entity_type': '',
}


class JobDetailApiPayload(TypedDict, total=False):
    """
    Unified Job Detail ``data`` envelope sections.

    Contract (stable top-level keys):
      - job
      - workflow
      - timeline
      - pod_cod
      - round_trip
      - alerts
      - sync_metadata
    """

    job: dict[str, Any]
    workflow: dict[str, Any]
    timeline: dict[str, Any]
    pod_cod: dict[str, Any]
    round_trip: dict[str, Any]
    alerts: dict[str, Any]
    sync_metadata: dict[str, Any]


@dataclass
class JobDetailResponseBuilder:
    """Assembles the canonical Job Detail API payload from orchestration context."""

    def build(self, context: JobDetailContext) -> JobDetailApiPayload:
        """
        Map context projections to the outward contract.

        TODO: enforce empty-move omission rules for ``pod_cod`` / ``round_trip``.
        """
        return JobDetailApiPayload(
            job=self._build_job(context),
            workflow=self._build_workflow(context),
            timeline=self._build_timeline(context),
            pod_cod=self._build_pod_cod(context),
            round_trip=self._build_round_trip(context),
            alerts=self._build_alerts(context),
            sync_metadata=self._build_sync_metadata(context),
        )

    def _build_job(self, context: JobDetailContext) -> dict[str, Any]:
        if context.job_header:
            return dict(context.job_header)
        return dict(_EMPTY_JOB)

    def _build_workflow(self, context: JobDetailContext) -> dict[str, Any]:
        return dict(context.workflow or {})

    def _build_timeline(self, context: JobDetailContext) -> dict[str, Any]:
        return dict(context.timeline or {})

    def _build_pod_cod(self, context: JobDetailContext) -> dict[str, Any]:
        # TODO: return {} for movement jobs at assembly time if not already omitted upstream.
        if context.job_type == 'movement':
            return {}
        return dict(context.pod_cod or {})

    def _build_round_trip(self, context: JobDetailContext) -> dict[str, Any]:
        if context.job_type == 'movement':
            return {}
        return dict(context.round_trip or {})

    def _build_alerts(self, context: JobDetailContext) -> dict[str, Any]:
        return dict(context.alerts or {})

    def _build_sync_metadata(self, context: JobDetailContext) -> dict[str, Any]:
        return dict(context.sync_metadata or {})
