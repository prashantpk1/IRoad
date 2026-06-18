"""Shared booking → booking-item → shipment linkage helpers for tenant forms."""


def build_booking_options_from_shipment_rows(shipment_rows):
    """Unique bookings derived from shipment linkage rows."""
    bookings = {}
    for row in shipment_rows:
        booking_id = (row.get('booking_id') or '').strip()
        if not booking_id:
            continue
        if booking_id not in bookings:
            bookings[booking_id] = {
                'booking_id': booking_id,
                'booking_no': row.get('booking_no') or '',
                'booking_items': set(),
            }
        booking_item = (row.get('booking_item') or '').strip()
        if booking_item:
            bookings[booking_id]['booking_items'].add(booking_item)

    options = []
    for booking_id, data in bookings.items():
        items = sorted(data['booking_items'])
        options.append(
            {
                'booking_id': data['booking_id'],
                'booking_no': data['booking_no'],
                'booking_item': items[0] if len(items) == 1 else '',
                'booking_item_summary': ', '.join(items),
            }
        )
    return sorted(options, key=lambda item: item['booking_no'], reverse=True)


def build_booking_item_options_from_shipment_rows(shipment_rows):
    """Booking items scoped per booking (Outbound/Backload may repeat across bookings)."""
    options = []
    seen = set()
    for row in shipment_rows:
        booking_id = (row.get('booking_id') or '').strip()
        booking_item = (row.get('booking_item') or '').strip()
        if not booking_item:
            continue
        item_key = (booking_id, booking_item)
        if item_key in seen:
            continue
        seen.add(item_key)
        options.append(
            {
                'booking_id': booking_id,
                'booking_no': row.get('booking_no') or '',
                'booking_item': booking_item,
                'pod_type': row.get('pod_type') or '',
            }
        )
    return options


def booking_option_matches(option_row, *, booking_id='', booking_no=''):
    """Return True when a linkage row matches the selected booking."""
    option_booking_id = (option_row.get('booking_id') or '').strip()
    option_booking_no = (option_row.get('booking_no') or '').strip()
    normalized_booking_id = (booking_id or '').strip()
    normalized_booking_no = (booking_no or '').strip()
    if not normalized_booking_id and not normalized_booking_no:
        return False
    if normalized_booking_id and option_booking_id == normalized_booking_id:
        return True
    if normalized_booking_no and option_booking_no == normalized_booking_no:
        return True
    return False


def shipment_option_matches(
    option_row,
    *,
    booking_id='',
    booking_no='',
    booking_item='',
):
    """Return True when a shipment row matches booking + booking item selection."""
    if not booking_option_matches(option_row, booking_id=booking_id, booking_no=booking_no):
        return False
    normalized_booking_item = (booking_item or '').strip()
    if not normalized_booking_item:
        return False
    return (option_row.get('booking_item') or '').strip() == normalized_booking_item
