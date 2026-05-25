"""
Per-request memoization for mobile job execution workflow calls.

Avoids duplicate ``get_allowed_driver_actions`` / allowed-id scans within one
HTTP request (authorize + membership + optional refresh).
"""
from __future__ import annotations

from typing import Any

_CACHE_ATTR = '_mobile_job_execution_workflow_cache'


def _bucket(request) -> dict | None:
    if request is None:
        return None
    cache = getattr(request, _CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(request, _CACHE_ATTR, cache)
    return cache


def _cache_key(
    *,
    driver_id,
    job_type: str,
    job_id: str,
    shipment_id,
    movement_id,
    exclude_log_id=None,
) -> str:
    return '|'.join(
        [
            str(driver_id or ''),
            job_type or '',
            job_id or '',
            str(shipment_id or ''),
            str(movement_id or ''),
            str(exclude_log_id or ''),
        ]
    )


def get_allowed_driver_actions_cached(
    request,
    *,
    driver,
    booking=None,
    shipment=None,
    movement=None,
    booking_item_type: str = '',
    exclude_log_id=None,
    include_action_id=None,
    job_type: str = '',
    job_id: str = '',
    job_no: str = '',
) -> dict[str, Any]:
    """Return allowed-actions payload; reuse in-request cache when present."""
    from iroad_tenants.services.operation_execution_service import (
        OperationExecutionService,
    )

    key = _cache_key(
        driver_id=getattr(driver, 'pk', None),
        job_type=job_type,
        job_id=job_id,
        shipment_id=getattr(shipment, 'pk', None) if shipment else None,
        movement_id=getattr(movement, 'pk', None) if movement else None,
        exclude_log_id=exclude_log_id,
    )
    cache = _bucket(request)
    if cache is not None and key in cache:
        return cache[key]

    payload = OperationExecutionService.get_allowed_driver_actions(
        booking=booking,
        shipment=shipment,
        movement=movement,
        booking_item_type=booking_item_type,
        exclude_log_id=exclude_log_id,
        include_action_id=include_action_id,
        request=request,
        job_type=job_type,
        job_id=job_id,
        job_no=job_no,
    )
    if cache is not None:
        cache[key] = payload
    return payload


def allowed_action_ids_from_payload(payload: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in (payload.get('actions') or []):
        if isinstance(item, dict) and item.get('action_id'):
            ids.add(str(item['action_id']))
    return ids


def invalidate_allowed_actions_cache(request) -> None:
    """Call after a successful execute so post-mutation refresh is fresh."""
    if request is None:
        return
    cache = getattr(request, _CACHE_ATTR, None)
    if isinstance(cache, dict):
        cache.clear()
