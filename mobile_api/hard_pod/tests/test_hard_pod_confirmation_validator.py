"""Tests for Hard POD page confirmation validation."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from mobile_api.hard_pod.exceptions import HardPodError
from mobile_api.hard_pod.services.hard_pod_confirmation_validator import (
    validate_confirmed_pages,
)


class HardPodConfirmationValidatorTests(TestCase):
    def setUp(self) -> None:
        self.shipment = SimpleNamespace(pk=uuid.uuid4(), shipment_no='SH-0009')

    @patch(
        'mobile_api.hard_pod.services.hard_pod_confirmation_validator.build_hard_pod_confirmation_context',
        return_value={
            'documents': [],
            'pages': [
                {
                    'page_id': 'page-1',
                    'document_id': 'doc-1',
                    'line_no': 1,
                    'label': 'DN-1020-P1',
                },
                {
                    'page_id': 'page-2',
                    'document_id': 'doc-1',
                    'line_no': 2,
                    'label': 'DN-1020-P2',
                },
            ],
        },
    )
    def test_requires_all_expected_pages(self, _mock_context):
        with self.assertRaises(HardPodError) as exc:
            validate_confirmed_pages(
                self.shipment,
                [{'page_id': 'page-1', 'document_id': 'doc-1', 'line_no': 1}],
                tenant_schema='tenant_test',
            )
        self.assertEqual(exc.exception.code, 'confirmed_pages_incomplete')

    @patch(
        'mobile_api.hard_pod.services.hard_pod_confirmation_validator.build_hard_pod_confirmation_context',
        return_value={
            'documents': [],
            'pages': [
                {
                    'page_id': 'page-1',
                    'document_id': 'doc-1',
                    'line_no': 1,
                    'label': 'DN-1020-P1',
                }
            ],
        },
    )
    def test_accepts_full_confirmation_set(self, _mock_context):
        rows = validate_confirmed_pages(
            self.shipment,
            [{'page_id': 'page-1', 'document_id': 'doc-1', 'line_no': 1}],
            tenant_schema='tenant_test',
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['label'], 'DN-1020-P1')
