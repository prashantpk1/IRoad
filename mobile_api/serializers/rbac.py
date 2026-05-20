"""
mobile_api/serializers/rbac.py

Read-only RBAC envelope helpers for mobile responses (profile, debug, etc.).
"""
from __future__ import annotations

from typing import Any

from mobile_api.rbac import build_mobile_rbac_snapshot


def serialize_mobile_rbac_permissions(request: Any) -> dict[str, Any]:
    """Return RBAC snapshot for embedding under ``permissions['rbac']``."""
    if request is None:
        return {}
    return build_mobile_rbac_snapshot(request)
