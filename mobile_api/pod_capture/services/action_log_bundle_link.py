"""
mobile_api/pod_capture/services/action_log_bundle_link.py

Bidirectional bundle ↔ Action Log linkage via ``source_ref`` (tenant Action Log).
"""
from __future__ import annotations

BUNDLE_SOURCE_PREFIX = 'pod_capture_bundle:'


def bundle_source_ref(bundle_id: str) -> str:
    return f'{BUNDLE_SOURCE_PREFIX}{(bundle_id or "").strip()}'


def parse_bundle_id_from_source_ref(source_ref: str) -> str | None:
    ref = (source_ref or '').strip()
    if not ref.startswith(BUNDLE_SOURCE_PREFIX):
        return None
    return ref[len(BUNDLE_SOURCE_PREFIX):].strip() or None


def link_action_log_to_bundle(action_log: object, bundle_id: str) -> None:
    """
    Persist capture bundle reference on Action Log (append-only metadata).

    Uses existing ``source_ref`` column — no tenant schema migration required.
    """
    if not bundle_id:
        return
    desired = bundle_source_ref(bundle_id)
    current = (getattr(action_log, 'source_ref', None) or '').strip()
    if current and current != desired:
        if parse_bundle_id_from_source_ref(current) == bundle_id:
            return
    if hasattr(action_log, 'source_ref'):
        action_log.source_ref = desired
        action_log.save(update_fields=['source_ref', 'updated_at'])
