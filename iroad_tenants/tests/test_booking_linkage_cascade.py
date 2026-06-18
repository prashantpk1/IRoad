import unittest

from iroad_tenants.booking_linkage_cascade import (
    booking_option_matches,
    build_booking_item_options_from_shipment_rows,
    build_booking_options_from_shipment_rows,
    shipment_option_matches,
)


class BookingLinkageCascadeTests(unittest.TestCase):
  def test_booking_item_options_are_scoped_per_booking(self):
    rows = [
      {
        'booking_id': 'b1',
        'booking_no': 'BK-001',
        'booking_item': 'Outbound',
        'shipment_id': 's1',
      },
      {
        'booking_id': 'b2',
        'booking_no': 'BK-002',
        'booking_item': 'Outbound',
        'shipment_id': 's2',
      },
      {
        'booking_id': 'b1',
        'booking_no': 'BK-001',
        'booking_item': 'Backload',
        'shipment_id': 's3',
      },
    ]
    options = build_booking_item_options_from_shipment_rows(rows)
    self.assertEqual(len(options), 3)
    self.assertEqual(
      sorted((row['booking_id'], row['booking_item']) for row in options),
      [('b1', 'Backload'), ('b1', 'Outbound'), ('b2', 'Outbound')],
    )

  def test_booking_options_summarize_items(self):
    rows = [
      {'booking_id': 'b1', 'booking_no': 'BK-001', 'booking_item': 'Outbound'},
      {'booking_id': 'b1', 'booking_no': 'BK-001', 'booking_item': 'Backload'},
    ]
    options = build_booking_options_from_shipment_rows(rows)
    self.assertEqual(len(options), 1)
    self.assertEqual(options[0]['booking_item_summary'], 'Backload, Outbound')
    self.assertEqual(options[0]['booking_item'], '')

  def test_shipment_match_requires_booking_item(self):
    row = {
      'booking_id': 'b1',
      'booking_no': 'BK-001',
      'booking_item': 'Outbound',
    }
    self.assertTrue(
      shipment_option_matches(
        row,
        booking_id='b1',
        booking_item='Outbound',
      )
    )
    self.assertFalse(
      shipment_option_matches(
        row,
        booking_id='b1',
        booking_item='Backload',
      )
    )
    self.assertFalse(
      shipment_option_matches(
        row,
        booking_id='b1',
        booking_item='',
      )
    )

  def test_booking_match_prefers_id(self):
    row = {'booking_id': 'b1', 'booking_no': 'BK-001'}
    self.assertTrue(booking_option_matches(row, booking_id='b1'))
    self.assertTrue(booking_option_matches(row, booking_no='BK-001'))
    self.assertFalse(booking_option_matches(row, booking_id='other'))


if __name__ == '__main__':
  unittest.main()
