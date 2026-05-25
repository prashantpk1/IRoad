"""
mobile_api/helpers/job_list_projections.py

Backward-compatible re-exports — prefer ``job_card_projections`` for new code.
"""
from __future__ import annotations

from mobile_api.helpers.job_card_projections import (
    build_movement_job_card_projection,
    build_shipment_job_card_projection,
    iso_job_timestamp,
    project_operational_indicators,
    project_route_from_movement,
    project_route_from_shipment,
    project_truck_summary_row,
)

# Legacy names used by older imports
build_job_route_projection = project_route_from_shipment
build_movement_location_projection = project_route_from_movement


def build_job_priority_flags(*, entity_type: str, shipment=None, movement=None):
    return project_operational_indicators(
        job_type=entity_type,  # type: ignore[arg-type]
        shipment=shipment,
        movement=movement,
    )


def build_latest_action_summary_placeholder():
    return None


def build_next_action_hint_for_shipment(shipment):
    from mobile_api.helpers.job_list_next_action import build_shipment_next_action_hint

    return build_shipment_next_action_hint(shipment)
