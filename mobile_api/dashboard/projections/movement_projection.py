"""
mobile_api/dashboard/projections/movement_projection.py

Pure functions: empty truck movement → dashboard ``current_empty_move`` card.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.dto.driver_empty_move_selection import (
    DriverEmptyMoveSelectionResult,
)
from mobile_api.dashboard.selectors import movement_selection_policy as policy
from mobile_api.job_detail.projections.job_location_projection import (
    build_movement_location_block,
)


def _empty_move_location_fields(
    movement: Any,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """From/to locations — same shape as Job Detail ``job.pickup_address`` / ``drop_address``."""
    block = build_movement_location_block(movement, request=request)
    return {
        'pickup_address': dict(block.get('pickup_address') or {}),
        'drop_address': dict(block.get('drop_address') or {}),
    }


def build_empty_move_card(
    movement: Any | None = None,
    *,
    selection: DriverEmptyMoveSelectionResult | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Map an empty move to the dashboard contract::

        {
            "movement_id": "",
            "job_id": "",
            "movement_no": "",
            "movement_stage": "",
            "movement_status": "",
            "progress_percentage": 0,
            "pickup_address": {},
            "drop_address": {}
        }
    """
    if movement is None and selection is None:
        return _empty_move_card()

    if selection is not None:
        movement = selection.movement
        live_status = str(getattr(movement, 'status', '') or '')
        if live_status and live_status != selection.movement_status:
            movement_stage = policy.movement_execution_stage(movement)
            progress_percentage = policy.movement_progress_percentage(movement)
            movement_status = live_status
        else:
            movement_stage = selection.movement_stage
            progress_percentage = selection.progress_percentage
            movement_status = live_status or selection.movement_status
        card = {
            'movement_id': str(
                getattr(movement, 'movement_id', None) or movement.pk or ''
            ),
            'movement_no': str(getattr(movement, 'movement_no', '') or ''),
            'movement_stage': movement_stage,
            'movement_status': movement_status,
            'progress_percentage': progress_percentage,
        }
        card['job_id'] = card['movement_id']
    else:
        card = {
            'movement_id': str(
                getattr(movement, 'movement_id', None) or movement.pk or ''
            ),
            'movement_no': str(getattr(movement, 'movement_no', '') or ''),
            'movement_stage': policy.movement_execution_stage(movement),
            'movement_status': str(getattr(movement, 'status', '') or ''),
            'progress_percentage': policy.movement_progress_percentage(movement),
        }
        card['job_id'] = card['movement_id']

    card.update(_empty_move_location_fields(movement, request=request))
    return card


def build_movement_summary(
    movement: Any | None,
    *,
    selection: DriverEmptyMoveSelectionResult | None = None,
) -> dict[str, Any]:
    """Extended read-only summary (workflow state, reason, operational label)."""
    if selection is not None:
        return dict(selection.summary)
    return policy.build_movement_summary(movement)


def build_movement_card(
    movement: Any,
    *,
    tenant_schema: str,
    is_empty_move: bool = False,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Map a movement to ``current_empty_move`` when ``is_empty_move`` is True.

    Laden shipment movements are not built here.
    """
    _ = tenant_schema
    if not is_empty_move or movement is None:
        return {}
    if policy.is_shipment_linked_loaded_movement(movement):
        return {}
    return build_empty_move_card(movement, request=request)
