"""
Operational helpers for Cargo Master (selection lists, validation).

Use ``active_cargo_for_client_qs`` when populating Shipment/Waybill cargo dropdowns:
only **Active** cargo, **Active** category, **Active** client (caller must pass client id).
"""
from tenant_workspace.models import TenantCargoMaster


def active_cargo_for_client_qs(client_account_id):
    """Cargo rows eligible for operational selection for one client."""
    return (
        TenantCargoMaster.active_objects.filter(client_account_id=client_account_id)
        .select_related('cargo_category', 'client_account')
        .order_by('display_name', 'cargo_code')
    )
