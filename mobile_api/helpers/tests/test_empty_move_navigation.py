"""Empty-move navigation metadata for mobile execute."""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.helpers.action_navigation_metadata import (
    apply_empty_move_navigation_to_action_row,
)


class EmptyMoveNavigationTests(SimpleTestCase):
    def test_apply_empty_move_navigation_sets_execute_action(self):
        row = {
            'action_code': 'OA-EM-002',
            'execution_label': 'Depart Empty',
            'execution_requirements': {'sequence_category': 'empty_move'},
        }
        out = apply_empty_move_navigation_to_action_row(row)
        self.assertEqual(out['action'], 'go_to_evidence_capture')
        self.assertEqual(out['screen'], 'evidence_capture')
        self.assertEqual(out['ui_mode'], 'empty_move')
        self.assertTrue(out['requires_evidence_capture'])
        self.assertFalse(out['direct_execute'])

    def test_apply_empty_move_navigation_for_catalog_category_only(self):
        row = {
            'action_code': 'OA-0014',
            'execution_label': 'Start Movement',
            'execution_requirements': {'sequence_category': 'empty_move'},
        }
        out = apply_empty_move_navigation_to_action_row(row)
        self.assertEqual(out['action'], 'go_to_evidence_capture')
        self.assertEqual(out['screen'], 'evidence_capture')
        self.assertEqual(out['ui_mode'], 'empty_move')
