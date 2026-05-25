"""
Tenant operation execution runtime (shared by portal views and mobile services).

Business rules are unchanged from the original portal implementation; logic is
centralized here so mobile APIs do not import view modules for side effects.
"""

from iroad_tenants.operation_runtime.side_effects import apply_execution_side_effects
from iroad_tenants.operation_runtime.latest_state import (
    derive_latest_action_status,
    sync_shipment_status_from_action_log,
    validate_shipment_status_transition,
)
from iroad_tenants.operation_runtime.idempotency import (
    find_recent_duplicate,
    normalize_idempotency_key,
    normalize_source_ref,
)

__all__ = [
    'apply_execution_side_effects',
    'derive_latest_action_status',
    'sync_shipment_status_from_action_log',
    'validate_shipment_status_transition',
    'find_recent_duplicate',
    'normalize_idempotency_key',
    'normalize_source_ref',
]
