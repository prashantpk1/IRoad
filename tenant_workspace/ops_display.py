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


def shipment_route_endpoints(shipment):
    """From/to labels for SIR and lists (FK addresses, then route_display)."""
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
    if from_loc or to_loc:
        return from_loc, to_loc
    route = (getattr(shipment, 'route_display', None) or '').strip()
    if not route:
        return '', ''
    for separator in (' → ', ' -> ', ' To ', ' to '):
        if separator in route:
            left, right = route.split(separator, 1)
            return left.strip(), right.strip()
    return route, ''
