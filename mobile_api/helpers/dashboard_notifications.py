"""
mobile_api/helpers/dashboard_notifications.py

Category/severity constants and mapping helpers for driver notification summary.
"""
from __future__ import annotations

CATEGORY_CRITICAL = 'critical'
CATEGORY_ASSIGNMENT = 'assignment'
CATEGORY_OPERATIONAL_WARNING = 'operational_warning'
CATEGORY_GENERAL = 'general'

SEVERITY_INFO = 'info'
SEVERITY_WARNING = 'warning'
SEVERITY_CRITICAL = 'critical'

# Push ``event_code`` hints → dashboard category (Phase 1 heuristic).
_PUSH_EVENT_CATEGORY_MAP: dict[str, str] = {
    'ASSIGNMENT': CATEGORY_ASSIGNMENT,
    'TRUCK_ASSIGNMENT': CATEGORY_ASSIGNMENT,
    'DRIVER_ASSIGNMENT': CATEGORY_ASSIGNMENT,
    'POD': CATEGORY_OPERATIONAL_WARNING,
    'POD_REQUIRED': CATEGORY_OPERATIONAL_WARNING,
    'COD': CATEGORY_OPERATIONAL_WARNING,
    'COD_COLLECTION': CATEGORY_OPERATIONAL_WARNING,
    'SHIPMENT_DELAY': CATEGORY_CRITICAL,
    'SYSTEM_ERROR': CATEGORY_CRITICAL,
}


def map_push_event_to_category(event_code: str | None) -> str:
    code = (event_code or '').strip().upper()
    if not code:
        return CATEGORY_GENERAL
    for prefix, category in _PUSH_EVENT_CATEGORY_MAP.items():
        if code == prefix or code.startswith(prefix):
            return category
    if 'CRITICAL' in code or 'URGENT' in code:
        return CATEGORY_CRITICAL
    if 'ASSIGN' in code:
        return CATEGORY_ASSIGNMENT
    if 'POD' in code or 'COD' in code or 'WARNING' in code:
        return CATEGORY_OPERATIONAL_WARNING
    return CATEGORY_GENERAL


def severity_for_category(category: str) -> str:
    if category == CATEGORY_CRITICAL:
        return SEVERITY_CRITICAL
    if category == CATEGORY_OPERATIONAL_WARNING:
        return SEVERITY_WARNING
    if category == CATEGORY_ASSIGNMENT:
        return SEVERITY_INFO
    return SEVERITY_INFO
