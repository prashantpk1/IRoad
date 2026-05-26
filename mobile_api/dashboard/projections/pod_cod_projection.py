"""
mobile_api/dashboard/projections/pod_cod_projection.py

Pure functions: shipment POD/COD state → ``pod_cod_summary`` dashboard block.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.selectors import pod_cod_policy as policy

_EMPTY_POD_COD_SUMMARY: dict[str, bool] = {
    'pod_pending': False,
    'pod_compliant': False,
    'hard_pod_pending': False,
    'cod_pending': False,
    'cod_collected': False,
    'treasury_pending': False,
    'delivery_blocked': False,
}


def build_pod_cod_summary(
    *,
    tenant_schema: str = '',
    shipment: Any | None = None,
    driver: Any | None = None,
    selection: DriverBookingSelectionResult | None = None,
    context: DriverDashboardContext | None = None,
) -> dict[str, bool]:
    """
    Build the ``pod_cod_summary`` section for the active shipment scope.

    Uses shipment column fields plus treasury/COD helpers — read-only.
    """
    _ = tenant_schema
    if context is not None:
        return build_pod_cod_summary_for_context(context)

    if selection is not None:
        return build_pod_cod_summary_from_booking_selection(
            selection,
            driver=driver,
        )

    if shipment is None:
        return dict(_EMPTY_POD_COD_SUMMARY)

    return dict(
        policy.derive_pod_cod_flags(
            shipment,
            driver=driver,
        )
    )


def build_pod_cod_summary_from_booking_selection(
    selection: DriverBookingSelectionResult,
    *,
    driver: Any | None = None,
) -> dict[str, bool]:
    """POD/COD flags for the active leg on the current booking job."""
    shipment = selection.active_shipment
    if shipment is None:
        return dict(_EMPTY_POD_COD_SUMMARY)
    return dict(
        policy.derive_pod_cod_flags(
            shipment,
            driver=driver,
        )
    )


def build_pod_cod_summary_for_context(
    context: DriverDashboardContext,
) -> dict[str, Any]:
    """
    POD/COD summary for dashboard orchestration context.

    Includes ``compliance_integrity`` when reconciliation has run.
    """
    shipment = context.active_shipment
    recon = context.reconciliation or {}
    compliance = dict(recon.get('compliance_integrity') or {})

    if shipment is None:
        out = dict(_EMPTY_POD_COD_SUMMARY)
        out['compliance_integrity'] = compliance or {
            'pod_reconciled': True,
            'cod_reconciled': True,
            'treasury_reconciled': True,
            'compliance_drift': False,
        }
        return out

    flags = dict(
        policy.derive_pod_cod_flags(
            shipment,
            driver=context.driver,
        )
    )
    flags['compliance_integrity'] = compliance or {
        'pod_reconciled': True,
        'cod_reconciled': True,
        'treasury_reconciled': True,
        'compliance_drift': False,
        'authority_source': 'columns_fallback',
    }
    return flags
