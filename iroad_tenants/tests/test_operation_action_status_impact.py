import unittest

from iroad_tenants.booking_status import (
    BOOKING_HEADER_CANCELLED,
    BOOKING_HEADER_COMPLETED,
    BOOKING_HEADER_CONFIRMED,
    BOOKING_HEADER_DRAFT,
    BOOKING_HEADER_IN_PROGRESS,
    BOOKING_HEADER_PARTIALLY_COMPLETED,
    OPERATION_ACTION_BOOKING_STATUS_CHOICES,
)
from iroad_tenants.operation_action_form import validate_status_impact_fields
from iroad_tenants.status_impact_resolution import (
    OPERATION_ACTION_MOVEMENT_STATUS_CHOICES,
    OPERATION_ACTION_SHIPMENT_STATUS_CHOICES,
    canonical_booking_status_impact_value,
    canonical_movement_status_impact_value,
    canonical_shipment_status_impact_value,
    is_valid_movement_status_impact,
    is_valid_shipment_status_impact,
    operation_action_booking_status_choices,
    resolve_booking_status_impact,
    resolve_movement_status_impact,
    resolve_shipment_status_impact,
)


class OperationActionStatusImpactTests(unittest.TestCase):
    def test_booking_dropdown_lists_all_standard_header_statuses(self):
        expected = {
            BOOKING_HEADER_DRAFT,
            BOOKING_HEADER_CONFIRMED,
            BOOKING_HEADER_IN_PROGRESS,
            BOOKING_HEADER_PARTIALLY_COMPLETED,
            BOOKING_HEADER_COMPLETED,
            BOOKING_HEADER_CANCELLED,
        }
        values = {value for value, _ in operation_action_booking_status_choices()}
        self.assertEqual(values, expected)
        self.assertEqual(len(OPERATION_ACTION_BOOKING_STATUS_CHOICES), 6)

    def test_shipment_dropdown_lists_all_standard_shipment_statuses(self):
        self.assertEqual(len(OPERATION_ACTION_SHIPMENT_STATUS_CHOICES), 8)

    def test_movement_dropdown_lists_all_standard_movement_statuses(self):
        self.assertEqual(len(OPERATION_ACTION_MOVEMENT_STATUS_CHOICES), 4)

    def test_resolve_booking_legacy_aliases(self):
        self.assertEqual(resolve_booking_status_impact('In_Execution'), 'in_progress')
        self.assertEqual(resolve_booking_status_impact('Executed'), 'completed')
        self.assertEqual(
            canonical_booking_status_impact_value('cancelled'),
            BOOKING_HEADER_CANCELLED,
        )

    def test_resolve_shipment_aliases_to_system_statuses(self):
        self.assertEqual(resolve_shipment_status_impact('In_Transit'), 'In Transit')
        self.assertEqual(
            canonical_shipment_status_impact_value('POD_Submitted'),
            'POD Submitted',
        )

    def test_resolve_movement_aliases_to_system_statuses(self):
        self.assertEqual(resolve_movement_status_impact('In_Progress'), 'In Progress')
        self.assertEqual(
            canonical_movement_status_impact_value('completed'),
            'Completed',
        )

    def test_validate_status_impact_allows_do_nothing(self):
        form_data = {
            'booking_status_impact': '',
            'shipment_status_impact': '',
            'movement_status_impact': '',
        }
        errors = validate_status_impact_fields(form_data)
        self.assertEqual(errors, {})
        self.assertEqual(form_data['booking_status_impact'], '')

    def test_validate_status_impact_canonicalizes_booking_selection(self):
        form_data = {
            'booking_status_impact': 'In_Execution',
            'shipment_status_impact': '',
            'movement_status_impact': '',
        }
        errors = validate_status_impact_fields(form_data)
        self.assertEqual(errors, {})
        self.assertEqual(form_data['booking_status_impact'], BOOKING_HEADER_IN_PROGRESS)

    def test_validate_status_impact_canonicalizes_shipment_selection(self):
        form_data = {
            'booking_status_impact': '',
            'shipment_status_impact': 'In_Transit',
            'movement_status_impact': '',
        }
        errors = validate_status_impact_fields(form_data)
        self.assertEqual(errors, {})
        self.assertEqual(form_data['shipment_status_impact'], 'In Transit')

    def test_validate_status_impact_rejects_invalid_booking_value(self):
        errors = validate_status_impact_fields(
            {
                'booking_status_impact': 'not-a-real-status',
                'shipment_status_impact': '',
                'movement_status_impact': '',
            }
        )
        self.assertIn('booking_status_impact', errors)

    def test_shipment_and_movement_validators_accept_system_values(self):
        self.assertTrue(is_valid_shipment_status_impact('Loaded'))
        self.assertTrue(is_valid_shipment_status_impact('In_Transit'))
        self.assertTrue(is_valid_movement_status_impact('Scheduled'))
        self.assertFalse(is_valid_shipment_status_impact('not-a-real-status'))


if __name__ == '__main__':
    unittest.main()
