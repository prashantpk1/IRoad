"""
mobile_api/hard_pod/dto/hard_pod_response_builder.py

API response envelope for Hard POD list (read-only).
"""
from __future__ import annotations

from typing import Any


class HardPodResponseBuilder:
    """Build ``data`` payload for Hard POD endpoints."""

    def list_pending(
        self,
        items: list[dict[str, Any]],
        *,
        tenant_schema: str,
    ) -> dict[str, Any]:
        return {
            'items': items,
            'count': len(items),
            'tenant_schema': tenant_schema,
        }

    def error_payload(
        self,
        *,
        code: str,
        message_key: str,
    ) -> dict[str, Any]:
        return {
            'error': True,
            'code': code,
            'message_key': message_key,
        }
