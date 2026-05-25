"""
mobile_api/helpers/job_list_next_action.py

Pure next-action hint builders for job list cards (no ORM, no per-row queries).
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from mobile_api.helpers.operational_status import MOVEMENT_ACTIVE_STATUSES


def build_shipment_next_action_hint(shipment) -> str | None:
    """
    Operational progression hint from shipment row fields only.

    Reuses dashboard POD/COD/status rules without action-log queries.
    """
    if shipment is None:
        return None
    from mobile_api.services.driver_dashboard_current_job import (
        build_next_action_hint,
    )

    return build_next_action_hint(shipment=shipment)


def build_movement_next_action_hint(
    movement,
    *,
    shipment=None,
) -> str | None:
    """
    Movement hint: linked shipment workflow first, else movement-status hint.
    """
    linked = shipment if shipment is not None else getattr(movement, 'shipment', None)
    if linked is not None:
        return build_shipment_next_action_hint(linked)

    status = (getattr(movement, 'status', None) or '').strip()
    if status not in MOVEMENT_ACTIVE_STATUSES:
        return None
    if status == 'Scheduled':
        return str(_('mobile.jobs.next_action.start_movement'))
    if status == 'In Progress':
        return str(_('mobile.jobs.next_action.complete_movement'))
    return None


def batch_build_shipment_next_action_hints(shipments: list) -> dict[str, str | None]:
    """Map ``shipment_id`` → hint (in-memory, no queries)."""
    out: dict[str, str | None] = {}
    for row in shipments:
        sid = str(getattr(row, 'shipment_id', None) or getattr(row, 'pk', ''))
        if sid:
            out[sid] = build_shipment_next_action_hint(row)
    return out


def batch_build_movement_next_action_hints(movements: list) -> dict[str, str | None]:
    """Map ``movement_id`` → hint (uses prefetched ``shipment`` when present)."""
    out: dict[str, str | None] = {}
    for row in movements:
        mid = str(getattr(row, 'movement_id', None) or getattr(row, 'pk', ''))
        if mid:
            out[mid] = build_movement_next_action_hint(row)
    return out
