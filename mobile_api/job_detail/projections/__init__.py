"""
mobile_api/job_detail/projections

Pure read-only projection functions for Job Detail response sections.

Shared strategy: delegate workflow authority to ``iroad_tenants`` operation runtime;
keep mobile-specific DTO shaping here (not in dashboard package).
"""

from mobile_api.job_detail.projections.job_header_projection import build_job_header
from mobile_api.job_detail.projections.pod_cod_projection import build_pod_cod_section
from mobile_api.job_detail.projections.round_trip_projection import (
    build_round_trip_section,
)
from mobile_api.job_detail.projections.sync_projection import build_sync_metadata
from mobile_api.job_detail.projections.timeline_projection import build_timeline_section
from mobile_api.job_detail.projections.workflow_projection import build_workflow_section

__all__ = [
    'build_job_header',
    'build_pod_cod_section',
    'build_round_trip_section',
    'build_sync_metadata',
    'build_timeline_section',
    'build_workflow_section',
]
