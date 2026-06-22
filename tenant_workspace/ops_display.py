"""Display helpers for operations FK relations (no denormalized string columns)."""


def client_account_label(client):
    if client is None:
        return ''
    return f'{client.account_no} - {client.display_name}'


def driver_label(driver):
    if driver is None:
        return ''
    name = driver.arabic_name or driver.english_name or ''
    if name:
        return f'{driver.driver_code} - {name}'
    return driver.driver_code or ''


def address_label(address):
    if address is None:
        return ''
    return f'{address.address_code} - {address.display_name}'


def location_label(location):
    if location is None:
        return ''
    return location.display_label or ''


def shipment_booking_no(shipment):
    if shipment is None:
        return ''
    if shipment.booking_id and shipment.booking:
        return shipment.booking.booking_no or ''
    return ''


def _split_route_display(route: str) -> tuple[str, str]:
    token = (route or '').strip()
    if not token:
        return '', ''
    for separator in (' → ', ' — ', ' – ', ' -> ', ' To ', ' to ', ' - '):
        if separator in token:
            left, right = token.split(separator, 1)
            return left.strip(), right.strip()
    return token, ''


def parse_route_display(route: str) -> tuple[str, str]:
    """Public helper — split ``route_display`` into origin/destination labels."""
    return _split_route_display(route)


def location_endpoint_label(location) -> str:
    """Human-readable location name for route endpoints (display label, not code)."""
    if location is None:
        return ''
    label = str(getattr(location, 'display_label', '') or '').strip()
    if label:
        return label
    return str(getattr(location, 'location_code', '') or '').strip()


def build_mobile_route_block(shipment, booking=None) -> dict[str, str]:
    """
    Route card for mobile History / Wallet — mirrors booking route master fields.

    Uses ``TenantRouteMaster`` on the booking when present; falls back to
    shipment/booking ``route_display`` and address endpoints.
    """
    booking_obj = booking if booking is not None else getattr(shipment, 'booking', None)
    route_master = getattr(booking_obj, 'route', None) if booking_obj is not None else None
    direction = (
        (getattr(booking_obj, 'route_direction', '') or 'forward').strip().lower()
        if booking_obj is not None
        else 'forward'
    )
    if direction not in {'forward', 'reverse'}:
        direction = 'forward'
    if shipment is not None and _booking_line_type(shipment) in {'backload', 'inbound'}:
        direction = 'reverse'

    route_id = ''
    route_code = ''
    route_label = ''
    route_type = ''
    route_display = ''
    route_display_start = ''
    route_display_end = ''

    if route_master is not None:
        route_id = str(getattr(route_master, 'route_id', '') or route_master.pk or '')
        route_code = str(getattr(route_master, 'route_code', '') or '')
        route_label = str(getattr(route_master, 'route_label', '') or '')
        route_type = str(getattr(route_master, 'route_type', '') or '')
        forward_start = location_endpoint_label(getattr(route_master, 'origin_point', None))
        forward_end = location_endpoint_label(getattr(route_master, 'destination_point', None))
        swap = direction == 'reverse'
        if shipment is not None and _booking_line_type(shipment) in {'backload', 'inbound'}:
            swap = not swap
        if swap:
            route_display_start, route_display_end = forward_end, forward_start
        else:
            route_display_start, route_display_end = forward_start, forward_end
        if route_display_start and route_display_end:
            route_display = f'{route_display_start} — {route_display_end}'
        else:
            route_display = route_label

    if not route_display:
        route_display = str(getattr(shipment, 'route_display', '') or '').strip()
        if not route_display and booking_obj is not None:
            route_display = str(getattr(booking_obj, 'route_display', '') or '').strip()

    parsed_from, parsed_to = parse_route_display(route_display)
    if not route_display_start and parsed_from:
        route_display_start = parsed_from
    if not route_display_end and parsed_to:
        route_display_end = parsed_to

    if not route_display_start or not route_display_end:
        from_label, to_label = shipment_route_endpoints(shipment, booking_obj)
        if not route_display_start and from_label:
            route_display_start = from_label.split(' - ', 1)[-1].strip() or from_label
        if not route_display_end and to_label:
            route_display_end = to_label.split(' - ', 1)[-1].strip() or to_label

    if not route_display and route_display_start and route_display_end:
        route_display = f'{route_display_start} — {route_display_end}'
    elif (
        shipment is not None
        and _booking_line_type(shipment) in {'backload', 'inbound'}
        and route_display_start
        and route_display_end
    ):
        route_display = f'{route_display_start} — {route_display_end}'
    if not route_label:
        route_label = route_display

    return {
        'route_display': route_display,
        'route_display_start': route_display_start,
        'route_display_end': route_display_end,
        'route_direction': direction if booking_obj is not None else '',
        'route_id': route_id,
        'route_code': route_code,
        'route_label': route_label,
        'route_type': route_type,
    }


def _booking_line_type(shipment) -> str:
    return str(getattr(shipment, 'booking_item_type', '') or '').strip().casefold()


def shipment_leg_addresses(shipment, booking=None):
    """
    Pickup and drop ``TenantAddressMaster`` rows for this shipment leg.

    Round trip swaps loading/delivery on backload/inbound legs (same rule as mobile
    ``resolve_leg_endpoint_addresses``).
    """
    if shipment is None:
        return None, None
    booking_obj = booking if booking is not None else getattr(shipment, 'booking', None)
    leg_is_backload = _booking_line_type(shipment) in {'backload', 'inbound'}

    loading = getattr(shipment, 'loading_address', None)
    delivery = getattr(shipment, 'delivery_address', None)
    if booking_obj is not None:
        if loading is None:
            loading = getattr(booking_obj, 'loading_address', None)
        if delivery is None:
            delivery = getattr(booking_obj, 'delivery_address', None)

    trip = str(getattr(booking_obj, 'trip_type', '') or '').strip().casefold()
    if trip == 'round' and (loading is not None or delivery is not None):
        if leg_is_backload:
            return delivery, loading
        return loading, delivery
    return loading, delivery


def shipment_route_endpoints(shipment, booking=None):
    """From/to labels for SIR, History, and Action Log (FK addresses, booking, route_display)."""
    if shipment is None:
        return '', ''
    from_loc = ''
    to_loc = ''
    loading = getattr(shipment, 'loading_address', None)
    delivery = getattr(shipment, 'delivery_address', None)
    if loading is not None:
        from_loc = address_label(loading)
    if delivery is not None:
        to_loc = address_label(delivery)

    booking_obj = booking if booking is not None else getattr(shipment, 'booking', None)
    if booking_obj is not None:
        if not from_loc and getattr(booking_obj, 'loading_address_id', None):
            from_loc = address_label(getattr(booking_obj, 'loading_address', None))
        if not to_loc and getattr(booking_obj, 'delivery_address_id', None):
            to_loc = address_label(getattr(booking_obj, 'delivery_address', None))

    if from_loc or to_loc:
        return from_loc, to_loc

    route = (getattr(shipment, 'route_display', None) or '').strip()
    if not route and booking_obj is not None:
        route = (getattr(booking_obj, 'route_display', None) or '').strip()
    return _split_route_display(route)


def address_city_label(address) -> str:
    """Short city/label for route pills when ``city`` alone is empty."""
    if address is None:
        return ''
    city = str(getattr(address, 'city', '') or '').strip()
    if city:
        return city
    display = str(
        getattr(address, 'display_name', '')
        or getattr(address, 'english_label', '')
        or getattr(address, 'address_code', '')
        or ''
    ).strip()
    return display


def resolve_shipment_truck(shipment, booking=None):
    """Truck on shipment leg, else booking line assignment."""
    truck = getattr(shipment, 'truck', None) if shipment is not None else None
    if truck is not None:
        return truck
    booking_obj = booking if booking is not None else getattr(shipment, 'booking', None)
    if booking_obj is None or shipment is None:
        return None
    if _booking_line_type(shipment) in {'backload', 'inbound'}:
        return getattr(booking_obj, 'booking_line_backload_truck', None)
    return getattr(booking_obj, 'assigned_truck', None)


def truck_display_block(truck) -> dict[str, str]:
    if truck is None:
        return {
            'truck_id': '',
            'truck_code': '',
            'plate_number': '',
        }
    return {
        'truck_id': str(getattr(truck, 'truck_id', '') or truck.pk or ''),
        'truck_code': str(getattr(truck, 'truck_code', '') or ''),
        'plate_number': str(getattr(truck, 'plate_number', '') or ''),
    }


def resolve_action_log_truck_code(action_log) -> str:
    truck = getattr(action_log, 'truck', None)
    if truck is not None:
        return str(getattr(truck, 'truck_code', '') or '').strip()
    shipment = getattr(action_log, 'shipment', None)
    if shipment is not None:
        shipment_truck = resolve_shipment_truck(shipment)
        if shipment_truck is not None:
            return str(getattr(shipment_truck, 'truck_code', '') or '').strip()
    movement = getattr(action_log, 'truck_movement', None)
    if movement is not None:
        movement_truck = getattr(movement, 'truck', None)
        if movement_truck is not None:
            return str(getattr(movement_truck, 'truck_code', '') or '').strip()
    return ''


def resolve_action_log_route(action_log) -> tuple[str, str]:
    shipment = getattr(action_log, 'shipment', None)
    if shipment is not None:
        from_loc, to_loc = shipment_route_endpoints(
            shipment,
            getattr(action_log, 'booking', None),
        )
        return from_loc or '-', to_loc or '-'

    movement = getattr(action_log, 'truck_movement', None)
    if movement is not None:
        from_loc = location_label(getattr(movement, 'from_location_point', None))
        to_loc = location_label(getattr(movement, 'to_location_point', None))
        return from_loc or '-', to_loc or '-'
    return '-', '-'
