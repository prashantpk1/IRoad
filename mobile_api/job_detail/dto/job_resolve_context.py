"""
mobile_api/job_detail/dto/job_resolve_context.py

Unified resolver output for explicit shipment / empty-move jobs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

JobType = Literal['shipment', 'movement']

WORKFLOW_SOURCE_ENTITY_RESOLVER = 'job_detail.entity_resolver'


@dataclass
class JobResolveContext:
    """
    Result of ``resolve_shipment_job`` / ``resolve_empty_move_job``.

    ``entity`` is a minimal identity dict; ``entity_row`` holds the ORM instance
    for orchestration (not serialized to clients directly).
    """

    job_type: JobType
    entity: dict[str, Any] = field(default_factory=dict)
    workflow_source: str = WORKFLOW_SOURCE_ENTITY_RESOLVER
    ownership_validated: bool = False

    entity_row: Any | None = None
    shipment: Any | None = None
    booking: Any | None = None

    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.ownership_validated and self.entity_row is not None

    def to_resolver_meta(self) -> dict[str, Any]:
        """Attach to ``JobDetailContext.resolver_meta``."""
        return {
            'job_type': self.job_type,
            'entity': dict(self.entity),
            'workflow_source': self.workflow_source,
            'ownership_validated': self.ownership_validated,
            'error_code': self.error_code,
            'error_message': self.error_message,
        }
