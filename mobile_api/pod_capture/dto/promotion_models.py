"""
mobile_api/pod_capture/dto/promotion_models.py

Execute-phase promotion contract (POD Capture does not create Action Logs).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PodPromotionScope:
    """Shipment-bound scope enforced at promotion time."""

    tenant_schema: str
    driver_id: str
    shipment_id: str

    def to_staging_scope(self, *, client_capture_id: str = '') -> Any:
        from mobile_api.pod_capture.dto.staging_models import StagingScope

        return StagingScope(
            tenant_schema=(self.tenant_schema or '').strip(),
            driver_id=(self.driver_id or '').strip(),
            shipment_id=(self.shipment_id or '').strip(),
            client_capture_id=(client_capture_id or '').strip(),
        )


@dataclass(frozen=True)
class PodPromotionRequest:
    """Input for :meth:`EvidencePromotionService.promote_staged_bundle`."""

    bundle_id: str
    action_log: Any
    scope: PodPromotionScope
    promotion_key: str = ''


@dataclass
class PodPromotionResult:
    """Outcome of one promotion attempt (including idempotent replay)."""

    bundle_id: str
    action_log_id: str
    media_row_ids: list[str] = field(default_factory=list)
    replayed: bool = False
    promoted_at: datetime | None = None
