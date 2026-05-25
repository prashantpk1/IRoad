"""
mobile_api/helpers/job_list_serialize.py

Fast path for job list responses — projections are already contract-shaped dicts.
"""
from __future__ import annotations

from typing import Any


def serialize_job_card_items(
    items: list[dict[str, Any]],
    *,
    serializer_class=None,
    use_fast_path: bool = True,
) -> list[dict[str, Any]]:
    """
    Return list payload for ``data.items``.

    Fast path trusts ``job_card_projections`` output (no DRF re-validation).
    """
    if use_fast_path or serializer_class is None:
        return items
    return serializer_class(items, many=True).data
