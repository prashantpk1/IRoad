import unittest
from unittest.mock import MagicMock, patch

from iroad_tenants.operation_action_form import (
    apply_confirmed_sequence_swap,
    default_mobile_visible_for_action_scope,
    format_job_operation_action_code,
    normalize_operation_action_sequencing,
    recommended_operation_action_code,
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

    def test_default_mobile_visible_for_driver_scopes(self):
        self.assertTrue(default_mobile_visible_for_action_scope('job'))
        self.assertTrue(default_mobile_visible_for_action_scope('on_call'))
        self.assertFalse(default_mobile_visible_for_action_scope('without'))

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

    def test_format_job_operation_action_code(self):
        self.assertEqual(format_job_operation_action_code(7), 'OA-0007')

    @patch('iroad_tenants.operation_action_form._max_existing_oa_action_suffix')
    @patch('iroad_tenants.operation_action_form.existing_sequenced_numbers')
    def test_recommended_operation_action_code_uses_max_suffix(
        self,
        mock_existing,
        mock_max_suffix,
    ):
        mock_existing.return_value = [1, 2, 3, 4, 5, 6, 7, 8]
        mock_max_suffix.return_value = 8
        self.assertEqual(recommended_operation_action_code('job'), 'OA-0009')

    @patch('iroad_tenants.operation_action_form._max_existing_oa_action_suffix')
    @patch('iroad_tenants.operation_action_form.existing_sequenced_numbers')
    def test_recommended_operation_action_code_empty_for_empty_move(
        self,
        mock_existing,
        mock_max_suffix,
    ):
        mock_existing.return_value = [1, 2]
        mock_max_suffix.return_value = 0
        self.assertEqual(recommended_operation_action_code('empty_move'), '')

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
            {
                'auto_movement_post': False,
                'sequence_category': 'job',
            },
            enabled_counts={
                'auto_movement_post': 0,
                'auto_shipment_post': 0,
                'auto_pod_post': 0,
                'hard_copy_collection': 0,
                'auto_treasury_post': 0,
            },
        )
        self.assertIn('auto_movement_post', errors)

    def test_toggle_rejects_second_auto_movement_post_in_same_category(self):
        errors = validate_configuration_toggles(
            {
                'auto_movement_post': True,
                'sequence_category': 'job',
            },
            enabled_counts={
                'auto_movement_post': 1,
                'auto_shipment_post': 0,
                'auto_pod_post': 0,
                'hard_copy_collection': 0,
                'auto_treasury_post': 0,
            },
        )
        self.assertIn('auto_movement_post', errors)

    def test_toggle_allows_auto_movement_post_when_other_category_owns_it(self):
        errors = validate_configuration_toggles(
            {
                'auto_movement_post': True,
                'sequence_category': 'empty_move',
            },
            enabled_counts={
                'auto_movement_post': 0,
                'auto_shipment_post': 0,
                'auto_pod_post': 0,
                'hard_copy_collection': 0,
                'auto_treasury_post': 0,
            },
        )
        self.assertNotIn('auto_movement_post', errors)

    def test_toggle_skips_auto_movement_post_requirement_for_without_category(self):
        errors = validate_configuration_toggles(
            {
                'auto_movement_post': False,
                'sequence_category': 'without',
            },
            enabled_counts={
                'auto_movement_post': 0,
                'auto_shipment_post': 0,
                'auto_pod_post': 0,
                'hard_copy_collection': 0,
                'auto_treasury_post': 0,
            },
        )
        self.assertNotIn('auto_movement_post', errors)

    def test_toggle_rejects_second_auto_shipment_post(self):
        errors = validate_configuration_toggles(
            {'auto_shipment_post': True},
            enabled_counts={
                'auto_movement_post': 1,
                'auto_shipment_post': 1,
                'auto_pod_post': 0,
                'hard_copy_collection': 0,
                'auto_treasury_post': 0,
            },
        )
        self.assertIn('auto_shipment_post', errors)

    def test_toggle_rejects_second_confirm_payment(self):
        errors = validate_configuration_toggles(
            {'auto_treasury_post': True},
            enabled_counts={
                'auto_movement_post': 1,
                'auto_shipment_post': 0,
                'auto_pod_post': 0,
                'hard_copy_collection': 0,
                'auto_treasury_post': 1,
            },
        )
        self.assertIn('auto_treasury_post', errors)

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

    def test_apply_confirmed_sequence_swap_on_edit_moves_peer_to_previous_slot(self):
        peer = MagicMock()
        peer.sequence_number = 1
        peer.auto_movement_post = True
        peer.auto_shipment_post = False
        current = MagicMock()
        current.sequence_number = 2

        form_data = {
            'sequence_category': 'job',
            'auto_movement_post': True,
            'auto_shipment_post': False,
        }

        apply_confirmed_sequence_swap(
            peer=peer,
            current_action=current,
            form_data=form_data,
        )

        self.assertEqual(peer.sequence_number, 2)
        self.assertTrue(peer.auto_movement_post)
        self.assertFalse(peer.auto_shipment_post)
        peer.save.assert_called_once_with(update_fields=['sequence_number', 'updated_at'])

    @patch('iroad_tenants.operation_action_form.next_sequence_slot')
    def test_apply_confirmed_sequence_swap_on_create_moves_peer_to_next_slot(
        self,
        mock_next_slot,
    ):
        mock_next_slot.return_value = 3
        peer = MagicMock()
        peer.pk = 'peer-id'
        peer.sequence_number = 1
        peer.auto_movement_post = True
        peer.auto_shipment_post = True
        peer.auto_pod_post = False
        peer.hard_copy_collection = False
        peer.auto_treasury_post = False

        other_owner = MagicMock()
        other_owner.pk = 'other-id'
        other_owner.auto_movement_post = True

        others_qs = MagicMock()
        others_qs.__iter__ = lambda self: iter([other_owner])
        others_qs.filter.return_value = others_qs

        mock_action_model = MagicMock()
        mock_action_model.objects.filter.return_value.exclude.return_value = others_qs

        form_data = {
            'sequence_category': 'job',
            'auto_movement_post': True,
            'auto_shipment_post': False,
        }

        with patch.dict(
            'sys.modules',
            {'tenant_workspace.models': MagicMock(TenantOperationAction=mock_action_model)},
        ):
            apply_confirmed_sequence_swap(
                peer=peer,
                current_action=None,
                form_data=form_data,
            )

        self.assertEqual(peer.sequence_number, 3)
        self.assertFalse(peer.auto_movement_post)
        self.assertFalse(peer.auto_shipment_post)
        mock_next_slot.assert_called_once()
        peer.save.assert_called_once_with(
            update_fields=[
                'sequence_number',
                'updated_at',
                'auto_movement_post',
                'auto_shipment_post',
            ]
        )
        self.assertFalse(other_owner.auto_movement_post)
        other_owner.save.assert_called_once_with(
            update_fields=['auto_movement_post', 'updated_at']
        )


if __name__ == '__main__':    unittest.main()
