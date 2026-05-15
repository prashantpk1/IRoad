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
