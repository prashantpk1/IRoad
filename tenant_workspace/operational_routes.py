"""
Operational route selection (booking, shipment, services, etc.).

Use ``TenantRouteMaster.eligible_for_operational_use`` or ``routes_for_operational_selection``
when populating route dropdowns so inactive routes and routes whose endpoints are no longer
active + serviceable never appear for new operational records.
"""

from __future__ import annotations


def routes_for_operational_selection():
    from tenant_workspace.models import TenantRouteMaster

    return TenantRouteMaster.eligible_for_operational_use.all()
