"""

Resolve the booking line used for atomic auto-shipment birth (A4).



Ensures round-trip backload inherits per-line POD doc count, COD, truck, and

addresses from the correct leg — not the first line without an active shipment.

"""

from __future__ import annotations



from typing import Any



from django.db.models import Q



from iroad_tenants.operation_runtime.booking_preshipment_cycle import (

    resolve_preshipment_booking_item_type,

)



_SECONDARY_LINE_TYPES = frozenset({'backload', 'inbound'})





def _norm_line(value: str | None) -> str:

    return (value or '').strip().casefold()





def booking_line_has_non_cancelled_shipment(

    booking: Any,

    booking_item_type: str,

    *,

    exclude_shipment_id=None,

) -> bool:

    """Whether a non-cancelled shipment row already exists for this booking leg."""

    from tenant_workspace.models import TenantShipment



    line = (booking_item_type or '').strip()

    if booking is None or not line:

        return False



    qs = TenantShipment.objects.filter(

        booking_id=booking.booking_id,

    ).exclude(shipment_status=TenantShipment.ShipmentStatus.CANCELLED)

    if exclude_shipment_id:

        qs = qs.exclude(pk=exclude_shipment_id)



    norm = _norm_line(line)

    if norm in _SECONDARY_LINE_TYPES:

        return qs.filter(

            Q(booking_item_type__iexact='Backload')

            | Q(booking_item_type__iexact='Inbound')

        ).exists()

    if norm == 'outbound':

        return qs.filter(

            Q(booking_item_type__iexact='Outbound')

            | Q(booking_item_type__iexact='Inbound')

        ).exists()

    return qs.filter(booking_item_type__iexact=line).exists()





def format_auto_shipment_birth_error(

    booking: Any,

    booking_item_type_hint: str = '',

) -> str:

    """Actionable validation message when auto-shipment birth cannot resolve a line."""

    if booking is None:

        return (

            'Auto Shipment Post requires a confirmed booking line without an active shipment.'

        )



    from iroad_tenants.views import (

        _tenant_booking_line_operational_status,

        _tenant_shipment_booking_line_rows,

    )



    leg = resolve_preshipment_booking_item_type(booking, booking_item_type_hint)

    if not _tenant_shipment_booking_line_rows(booking):

        return (

            'Auto Shipment Post requires a confirmed booking line without an active shipment. '

            'This booking has no executable leg rows.'

        )



    if _tenant_booking_line_operational_status(booking, leg) == 'Cancelled':

        return (

            f'Auto Shipment Post cannot create a shipment for the {leg} leg because that '

            'booking line is cancelled.'

        )



    if booking_line_has_non_cancelled_shipment(booking, leg):

        return (

            f'A shipment already exists for the {leg} leg. Refresh the dashboard and continue '

            'on job_type=shipment for that leg — do not run Confirm Loaded on the booking '

            'job again.'

        )



    return (

        'Auto Shipment Post requires a confirmed booking line without an active shipment. '

        f'Target leg: {leg or "unknown"}. Complete Start Job, Pickup Arrival, and Start '

        'Loading for this leg, then refresh the dashboard before Confirm Loaded.'

    )





def resolve_auto_shipment_target_line(

    booking: Any,

    *,

    booking_item_type_hint: str = '',

) -> dict[str, Any] | None:

    """Pick the booking line row for ``_tenant_shipment_birth_from_booking_line``."""

    if booking is None:

        return None



    from iroad_tenants.views import (

        _tenant_booking_line_operational_status,

        _tenant_shipment_booking_line_rows,

        _tenant_shipment_match_booking_line,

    )



    def _line_is_birth_eligible(line: dict[str, Any]) -> bool:

        line_type = (line.get('booking_item_type') or '').strip()

        if not line_type:

            return False

        if _tenant_booking_line_operational_status(booking, line_type) == 'Cancelled':

            return False

        return not booking_line_has_non_cancelled_shipment(booking, line_type)



    leg = resolve_preshipment_booking_item_type(booking, booking_item_type_hint)

    if leg and _tenant_booking_line_operational_status(booking, leg) == 'Cancelled':

        leg = resolve_preshipment_booking_item_type(booking, '')



    if leg:

        matched = _tenant_shipment_match_booking_line(

            booking,

            booking_item_type=leg,

        )

        if matched is not None and _line_is_birth_eligible(matched):

            return matched



    for line in _tenant_shipment_booking_line_rows(booking):

        line_type = (line.get('booking_item_type') or '').strip()

        if leg and line_type != leg:

            continue

        if _line_is_birth_eligible(line):

            return line



    return None


