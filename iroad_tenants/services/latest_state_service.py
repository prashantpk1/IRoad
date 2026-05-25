"""Latest operational state derivation — logs-first reconciliation."""

from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.latest_state import (
    derive_latest_action_status,
    sync_shipment_status_from_action_log,
    validate_shipment_status_transition,
)
from iroad_tenants.operation_runtime.impacts import resolve_shipment_status_impact
from iroad_tenants.operation_runtime.workflow_state_reconciler import (
    reconcile_job_execution_state,
    reconcile_movement_execution_state,
    reconcile_shipment_execution_state,
    validate_shipment_state_consistency,
)


class LatestStateService:
    """
    Unified latest-state API for portal and mobile job detail.

    Authoritative progression is derived from **action logs**; the shipment/movement
    column is a cache compared via ``drift`` metadata.
    """

    reconcile_shipment_execution_state = staticmethod(reconcile_shipment_execution_state)
    reconcile_movement_execution_state = staticmethod(reconcile_movement_execution_state)
    reconcile_job_execution_state = staticmethod(reconcile_job_execution_state)
    validate_shipment_state_consistency = staticmethod(validate_shipment_state_consistency)

    @staticmethod
    def derive_latest_execution_state(
        shipment,
        *,
        movement=None,
        driver_id=None,
        exclude_log_id=None,
        request=None,
    ) -> dict[str, Any]:
        """Shipment-scoped execution state (logs-first)."""
        if shipment is None:
            return {
                'shipment_status': None,
                'derived_status': None,
                'operational_stage': None,
                'in_sync': True,
                'state_source': 'action_logs',
            }
        state = reconcile_shipment_execution_state(
            shipment,
            movement=movement,
            driver_id=driver_id,
            exclude_log_id=exclude_log_id,
            request=request,
        )
        return _public_execution_state(state)

    @staticmethod
    def derive_movement_execution_state(
        movement,
        *,
        driver_id=None,
        exclude_log_id=None,
        request=None,
    ) -> dict[str, Any]:
        if movement is None:
            return {
                'movement_status': None,
                'derived_status': None,
                'operational_stage': None,
                'in_sync': True,
                'state_source': 'action_logs',
            }
        state = reconcile_movement_execution_state(
            movement,
            driver_id=driver_id,
            exclude_log_id=exclude_log_id,
            request=request,
        )
        return _public_execution_state(state)

    @staticmethod
    def derive_job_execution_state(
        *,
        shipment=None,
        movement=None,
        driver_id=None,
        exclude_log_id=None,
        request=None,
    ) -> dict[str, Any]:
        state = reconcile_job_execution_state(
            shipment=shipment,
            movement=movement,
            driver_id=driver_id,
            exclude_log_id=exclude_log_id,
            request=request,
        )
        return _public_execution_state(state)

    @staticmethod
    def derive_latest_action_status(shipment):
        return derive_latest_action_status(shipment)

    @staticmethod
    def sync_shipment_status_from_action_log(shipment):
        return sync_shipment_status_from_action_log(shipment)

    @staticmethod
    def repair_shipment_column_from_logs(shipment, *, movement=None) -> dict[str, Any]:
        """
        Align ``shipment_status`` column with log-authoritative status when drift detected.
        """
        before = reconcile_shipment_execution_state(shipment, movement=movement)
        if not (before.get('drift') or {}).get('has_status_drift'):
            return {'repaired': False, 'state': before}
        sync_shipment_status_from_action_log(shipment)
        shipment.refresh_from_db()
        after = reconcile_shipment_execution_state(shipment, movement=movement)
        return {'repaired': True, 'state': after}

    @staticmethod
    def validate_shipment_status_transition(shipment, new_status) -> None:
        validate_shipment_status_transition(shipment, new_status)

    @staticmethod
    def resolve_shipment_status_impact(raw_value):
        return resolve_shipment_status_impact(raw_value)


def _public_execution_state(state: dict[str, Any]) -> dict[str, Any]:
    """Stable keys for mobile serializers + extended drift metadata."""
    drift = state.get('drift') or {}
    return {
        'entity_type': state.get('entity_type'),
        'shipment_status': state.get('shipment_status'),
        'movement_status': state.get('movement_status'),
        'column_status': state.get('column_status') or state.get('shipment_status'),
        'derived_status': state.get('derived_status') or state.get('authoritative_status'),
        'authoritative_status': state.get('authoritative_status'),
        'hybrid_latest_log_status': state.get('hybrid_latest_log_status'),
        'execution_sub_stage': state.get('execution_sub_stage'),
        'operational_stage': state.get('operational_stage'),
        'in_sync': bool(state.get('in_sync', True)),
        'state_source': state.get('state_source', 'action_logs'),
        'drift': drift,
        'timeline': state.get('timeline') or {},
        'latest_action': state.get('latest_action'),
        'has_drift': bool(drift.get('has_drift')),
    }
