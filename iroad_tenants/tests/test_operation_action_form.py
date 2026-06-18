import unittest
from unittest.mock import MagicMock, patch

from iroad_tenants.operation_action_form import (
    apply_confirmed_sequence_swap,
    normalize_operation_action_sequencing,
    recommended_sequence_number,
    sequence_category_field_active,
    sequence_number_field_active,
    sequencing_is_active,
    validate_configuration_toggles,
    validate_consecutive_sequence_numbers,
    validate_operation_action_sequencing,
    validate_sequence_number_placement,
)

class OperationActionFormTests(unittest.TestCase):
    def test_activation_rule_scope_without(self):
        self.assertFalse(sequence_category_field_active('without'))
        self.assertFalse(sequence_number_field_active('without', 'job'))
        data = {
            'action_scope': 'without',
            'sequence_category': 'job',
            'sequence_number': '5',
        }
        normalize_operation_action_sequencing(data)
        self.assertEqual(data['sequence_category'], 'without')
        self.assertEqual(data['sequence_number'], '1')

    def test_activation_rule_category_without(self):
        self.assertTrue(sequence_category_field_active('job'))
        self.assertFalse(sequence_number_field_active('job', 'without'))
        self.assertFalse(sequencing_is_active('job', 'without'))
        data = {
            'action_scope': 'job',
            'sequence_category': 'without',
            'sequence_number': '5',
        }
        normalize_operation_action_sequencing(data)
        self.assertEqual(data['sequence_category'], '')
        self.assertEqual(data['sequence_number'], '1')

    def test_sequencing_active_for_job_scope_and_category(self):
        self.assertTrue(sequencing_is_active('job', 'job'))
        self.assertTrue(sequencing_is_active('on_call', 'empty_move'))

    def test_consecutive_sequence_numbers_valid(self):
        self.assertIsNone(validate_consecutive_sequence_numbers([1, 2, 3]))

    def test_consecutive_sequence_numbers_rejects_gap(self):
        error = validate_consecutive_sequence_numbers([1, 2, 4])
        self.assertIn('consecutively', error or '')

    def test_consecutive_sequence_numbers_rejects_duplicate(self):
        error = validate_consecutive_sequence_numbers([1, 2, 2])
        self.assertIn('unique', error or '')

    def test_consecutive_sequence_numbers_rejects_starting_above_one(self):
        error = validate_consecutive_sequence_numbers([2, 3])
        self.assertIn('consecutively', error or '')

    @patch('iroad_tenants.operation_action_form.existing_sequenced_numbers')
    def test_recommended_sequence_number_returns_next_slot(self, mock_existing):
        mock_existing.return_value = [1, 2]
        self.assertEqual(recommended_sequence_number('job'), 3)

    @patch('iroad_tenants.operation_action_form.existing_sequenced_numbers')
    def test_recommended_sequence_number_returns_one_for_empty_category(self, mock_existing):
        mock_existing.return_value = []
        self.assertEqual(recommended_sequence_number('job'), 1)

    @patch('iroad_tenants.operation_action_form.find_sequence_peer')
    @patch('iroad_tenants.operation_action_form.existing_sequenced_numbers')
    def test_validate_sequence_number_rejects_gap(self, mock_existing, mock_find_peer):
        mock_existing.return_value = [1, 2]
        mock_find_peer.return_value = None
        error = validate_sequence_number_placement('job', 4)
        self.assertIn('next available value (3)', error or '')

    @patch('iroad_tenants.operation_action_form.find_sequence_peer')
    @patch('iroad_tenants.operation_action_form.existing_sequenced_numbers')
    def test_validate_sequence_number_allows_next_slot(self, mock_existing, mock_find_peer):
        mock_existing.return_value = [1, 2]
        mock_find_peer.return_value = None
        self.assertIsNone(validate_sequence_number_placement('job', 3))

    @patch('iroad_tenants.operation_action_form.find_sequence_peer')
    @patch('iroad_tenants.operation_action_form.existing_sequenced_numbers')
    def test_validate_sequencing_rejects_without_category_for_job_scope(self, mock_existing, mock_find_peer):
        mock_existing.return_value = []
        mock_find_peer.return_value = None
        errors, sequence_number = validate_operation_action_sequencing(
            {
                'action_scope': 'job',
                'sequence_category': 'without',
                'sequence_number': '',
            }
        )
        self.assertIn('sequence_category', errors)
        self.assertEqual(sequence_number, 1)

    @patch('iroad_tenants.operation_action_form.find_sequence_peer')
    @patch('iroad_tenants.operation_action_form.existing_sequenced_numbers')
    def test_validate_sequencing_requires_number_when_active(self, mock_existing, mock_find_peer):
        mock_existing.return_value = []
        mock_find_peer.return_value = None
        errors, _ = validate_operation_action_sequencing(
            {
                'action_scope': 'job',
                'sequence_category': 'job',
                'sequence_number': '',
            }
        )
        self.assertIn('sequence_number', errors)

    def test_toggle_requires_exactly_one_auto_movement_post(self):
        errors = validate_configuration_toggles(
            {'auto_movement_post': False},
            enabled_counts={
                'auto_movement_post': 0,
                'auto_shipment_post': 0,
                'auto_pod_post': 0,
                'hard_copy_collection': 0,
            },
        )
        self.assertIn('auto_movement_post', errors)

    def test_toggle_rejects_second_auto_movement_post(self):
        errors = validate_configuration_toggles(
            {'auto_movement_post': True},
            enabled_counts={
                'auto_movement_post': 1,
                'auto_shipment_post': 0,
                'auto_pod_post': 0,
                'hard_copy_collection': 0,
            },
        )
        self.assertIn('auto_movement_post', errors)

    def test_toggle_rejects_second_auto_shipment_post(self):
        errors = validate_configuration_toggles(
            {'auto_shipment_post': True},
            enabled_counts={
                'auto_movement_post': 1,
                'auto_shipment_post': 1,
                'auto_pod_post': 0,
                'hard_copy_collection': 0,
            },
        )
        self.assertIn('auto_shipment_post', errors)

    @patch('iroad_tenants.operation_action_form.find_sequence_peer')
    @patch('iroad_tenants.operation_action_form.existing_sequenced_numbers')
    def test_duplicate_sequence_requires_swap_confirmation(
        self,
        mock_existing_numbers,
        mock_find_peer,
    ):
        peer = MagicMock()
        peer.english_label = 'Start Job'
        mock_find_peer.return_value = peer
        mock_existing_numbers.return_value = [1, 2]

        form_data = {
            'action_scope': 'job',
            'sequence_category': 'job',
            'sequence_number': '1',
            'confirm_sequence_swap': False,
        }
        errors, _ = validate_operation_action_sequencing(form_data)
        self.assertIn('sequence_number', errors)
        self.assertIn('Confirm swap', errors['sequence_number'])

    @patch('iroad_tenants.operation_action_form.find_sequence_peer')
    @patch('iroad_tenants.operation_action_form.existing_sequenced_numbers')
    def test_duplicate_sequence_allowed_when_swap_confirmed(
        self,
        mock_existing_numbers,
        mock_find_peer,
    ):
        peer = MagicMock()
        peer.english_label = 'Start Job'
        mock_find_peer.return_value = peer
        mock_existing_numbers.return_value = [1, 2]

        form_data = {
            'action_scope': 'job',
            'sequence_category': 'job',
            'sequence_number': '1',
            'confirm_sequence_swap': True,
        }
        errors, sequence_number = validate_operation_action_sequencing(form_data)
        self.assertNotIn('sequence_number', errors)
        self.assertEqual(sequence_number, 1)

    def test_apply_confirmed_sequence_swap_on_edit_exchanges_impact_with_peer(self):
        peer = MagicMock()
        peer.sequence_number = 1
        peer.auto_movement_post = False
        peer.auto_shipment_post = True
        peer.auto_pod_post = False
        peer.hard_copy_collection = False
        peer.booking_status_impact = ''
        peer.shipment_status_impact = ''
        peer.movement_status_impact = ''
        current = MagicMock()
        current.sequence_number = 2

        form_data = {
            'sequence_category': 'job',
            'auto_movement_post': True,
            'auto_shipment_post': False,
            'auto_pod_post': False,
            'hard_copy_collection': False,
            'booking_status_impact': '',
            'shipment_status_impact': '',
            'movement_status_impact': '',
        }

        apply_confirmed_sequence_swap(
            peer=peer,
            current_action=current,
            form_data=form_data,
        )

        self.assertEqual(peer.sequence_number, 2)
        self.assertTrue(peer.auto_movement_post)
        self.assertFalse(peer.auto_shipment_post)
        self.assertFalse(form_data['auto_movement_post'])
        self.assertTrue(form_data['auto_shipment_post'])
        peer.save.assert_called_once()

    @patch('iroad_tenants.operation_action_form.next_sequence_slot')
    def test_apply_confirmed_sequence_swap_on_create_exchanges_impact_and_moves_peer(
        self,
        mock_next_slot,
    ):
        mock_next_slot.return_value = 3
        peer = MagicMock()
        peer.sequence_number = 1
        peer.auto_movement_post = True
        peer.auto_shipment_post = False
        peer.auto_pod_post = False
        peer.hard_copy_collection = False
        peer.booking_status_impact = ''
        peer.shipment_status_impact = ''
        peer.movement_status_impact = ''

        form_data = {
            'sequence_category': 'job',
            'auto_movement_post': False,
            'auto_shipment_post': True,
            'auto_pod_post': False,
            'hard_copy_collection': False,
            'booking_status_impact': '',
            'shipment_status_impact': '',
            'movement_status_impact': '',
        }

        apply_confirmed_sequence_swap(
            peer=peer,
            current_action=None,
            form_data=form_data,
        )

        self.assertEqual(peer.sequence_number, 3)
        self.assertFalse(peer.auto_movement_post)
        self.assertTrue(peer.auto_shipment_post)
        self.assertTrue(form_data['auto_movement_post'])
        self.assertFalse(form_data['auto_shipment_post'])
        mock_next_slot.assert_called_once()
        peer.save.assert_called_once()


if __name__ == '__main__':    unittest.main()
