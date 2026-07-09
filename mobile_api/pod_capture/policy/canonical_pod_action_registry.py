"""
mobile_api/pod_capture/policy/canonical_pod_action_registry.py

Canonical IRoute Action Master semantics for POD / delivery compliance.

Fixes inconsistent interpretations where A7 was treated as both "Upload POD"
and "Delivered", and A8 as POD upload instead of unloading.

Reference mapping (IRoute Ch.2)::

    A7  → Upload POD / POD evidence (``pod_upload``)
    A8  → Unloading at delivery site (``unloading``) — not POD upload
    Delivered → ``shipment_status_impact`` → Delivered (``delivered_status``)

Consumers (dashboard reconciler, timeline, POD capture) must use this module
instead of ad-hoc ``operation_action_matches`` needle lists.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from iroad_tenants.operation_runtime.impacts import (
    operation_action_matches,
    resolve_shipment_status_impact,
)
from tenant_workspace.models import TenantShipment

# Canonical short codes (case-insensitive substring match on code + english label).
A7_UPLOAD_POD_NEEDLES = ('a7', 'action 7', 'upload pod')
A8_UNLOADING_NEEDLES = ('a8', 'action 8', 'unloading')
A9_COD_NEEDLES = ('a9', 'action 9', 'collect payment', 'cod')

POD_UPLOAD_LABEL_NEEDLES = (
    'pod',
    'submit pod',
    'proof of delivery',
    'capture pod',
)

DELIVERED_STATUS_NEEDLES = ('delivered', 'delivery complete', 'mark delivered')
HARD_POD_NEEDLES = ('hard pod', 'hard copy', 'hard-copy', 'hardcopy', 'delivery note')


class PodActionRole(str, Enum):
    """Semantic roles — independent of tenant-specific action_code strings."""

    POD_UPLOAD = 'pod_upload'
    UNLOADING = 'unloading'
    DELIVERED_STATUS = 'delivered_status'
    HARD_POD = 'hard_pod'
    COD_COLLECT = 'cod_collect'
    OTHER = 'other'


def classify_pod_action_role(action: Any | None) -> PodActionRole:
    if action is None:
        return PodActionRole.OTHER

    if is_cod_collect_action(action):
        return PodActionRole.COD_COLLECT
    # Combined Upload POD (digital + hard copy) logs as digital upload until custody promotes.
    if is_pod_upload_action(action) and (
        getattr(action, 'auto_pod_post', False)
        and getattr(action, 'hard_copy_collection', False)
    ):
        return PodActionRole.POD_UPLOAD
    if is_hard_pod_action(action):
        return PodActionRole.HARD_POD
    if is_delivered_status_action(action):
        return PodActionRole.DELIVERED_STATUS
    if is_pod_upload_action(action):
        return PodActionRole.POD_UPLOAD
    if is_unloading_action(action):
        return PodActionRole.UNLOADING
    return PodActionRole.OTHER


def action_has_role(action: Any | None, role: PodActionRole) -> bool:
    return classify_pod_action_role(action) == role


def is_pod_upload_action(action: Any | None) -> bool:
    """Upload POD — ``auto_pod_post`` or POD label; not unloading / hard-copy-only rows."""
    if action is None:
        return False
    if getattr(action, 'auto_pod_post', False):
        return True
    # Hard-copy-only rows (hidden A7H) are not digital upload — unless the row
    # is still the tenant Upload POD action (label / A7 needles).
    if getattr(action, 'hard_copy_collection', False) and not getattr(
        action, 'auto_pod_post', False
    ):
        if operation_action_matches(action, *A7_UPLOAD_POD_NEEDLES):
            return True
        if operation_action_matches(action, *POD_UPLOAD_LABEL_NEEDLES):
            return True
        return False
    if operation_action_matches(action, *A7_UPLOAD_POD_NEEDLES):
        return True
    return operation_action_matches(action, *POD_UPLOAD_LABEL_NEEDLES)


def is_unloading_action(action: Any | None) -> bool:
    """A8 — unloading; explicitly **not** POD upload."""
    if action is None:
        return False
    return operation_action_matches(action, *A8_UNLOADING_NEEDLES)


def is_delivered_status_action(action: Any | None) -> bool:
    """
    Shipment transition to Delivered — must **not** use A7 needles.

    Uses ``shipment_status_impact`` resolution first, then deliver/delivered labels
    without matching A7 upload pod tokens.
    """
    if action is None:
        return False
    if (getattr(action, 'action_code', '') or '').strip().upper() == 'A_POD_VERIFY':
        return True
    impact = resolve_shipment_status_impact(
        (getattr(action, 'shipment_status_impact', None) or '').strip()
    )
    if impact == TenantShipment.ShipmentStatus.DELIVERED:
        return True
    if operation_action_matches(action, *A7_UPLOAD_POD_NEEDLES):
        return False
    return operation_action_matches(action, *DELIVERED_STATUS_NEEDLES)


def is_hard_pod_action(action: Any | None) -> bool:
    if action is None:
        return False
    if getattr(action, 'hard_copy_collection', False):
        return True
    return operation_action_matches(action, *HARD_POD_NEEDLES)


def is_cod_collect_action(action: Any | None) -> bool:
    if action is None:
        return False
    return operation_action_matches(action, *A9_COD_NEEDLES)


# Timeline taxonomy (Job Detail) — single source; do not duplicate A7/A8 needles elsewhere.
TIMELINE_EVENT_POD = 'pod'
TIMELINE_EVENT_HARD_POD = 'hard_pod'
TIMELINE_EVENT_COD = 'cod'
TIMELINE_EVENT_MOVEMENT = 'movement'
TIMELINE_EVENT_DELAY = 'delay'
TIMELINE_EVENT_ISSUE = 'issue'
TIMELINE_EVENT_ACTION = 'action'


def classify_timeline_event_type(action: Any | None) -> str:
    """
    Canonical timeline classification.

    A7 → POD evidence (``pod``). A8 → unloading (``movement``), never POD.
    """
    if action is None:
        return TIMELINE_EVENT_ACTION

    from iroad_tenants.operation_runtime.impacts import operation_action_matches

    if operation_action_matches(
        action,
        'delay',
        'delayed',
        'late arrival',
        'traffic delay',
        'waiting',
    ):
        return TIMELINE_EVENT_DELAY

    if operation_action_matches(
        action,
        'issue',
        'incident',
        'problem',
        'breakdown',
        'accident',
        'complaint',
    ):
        return TIMELINE_EVENT_ISSUE

    if is_hard_pod_action(action):
        return TIMELINE_EVENT_HARD_POD

    if is_cod_collect_action(action):
        return TIMELINE_EVENT_COD

    if is_pod_upload_action(action):
        return TIMELINE_EVENT_POD

    if is_unloading_action(action):
        return TIMELINE_EVENT_MOVEMENT

    if (getattr(action, 'movement_status_impact', None) or '').strip() or operation_action_matches(
        action,
        'movement',
        'empty move',
        'depart yard',
        'arrive',
        'start move',
    ):
        return TIMELINE_EVENT_MOVEMENT

    return TIMELINE_EVENT_ACTION
