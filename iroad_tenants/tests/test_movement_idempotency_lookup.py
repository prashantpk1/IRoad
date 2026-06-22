"""Movement idempotency must not replay via source_ref alone."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.services.action_execution_service import ActionExecutionService


class MovementIdempotencyLookupTests(SimpleTestCase):
    @patch('iroad_tenants.services.action_execution_service.TenantOperationActionLog')
    def test_movement_ignores_source_ref_without_matching_key(self, mock_model):
        movement_id = uuid4()
        movement = SimpleNamespace(pk=movement_id)
        stale_log = SimpleNamespace(
            pk=uuid4(),
            truck_movement_id=movement_id,
            idempotency_key='em-depart-old-key',
        )

        def _filter(**kwargs):
            qs = MagicMock()
            if kwargs.get('source_ref'):
                qs.first.return_value = stale_log
            else:
                qs.first.return_value = None
            return qs

        mock_model.objects.filter.side_effect = _filter

        result = ActionExecutionService._find_idempotent_existing(
            idempotency_key='em-depart-brand-new-key',
            source_channel='mobile_driver',
            source_ref=f'movement:{movement_id}:EM2',
            movement=movement,
            job_type='movement',
        )
        self.assertIsNone(result)

    @patch('iroad_tenants.services.action_execution_service.TenantOperationActionLog')
    def test_movement_replays_same_key_on_same_movement(self, mock_model):
        movement_id = uuid4()
        movement = SimpleNamespace(pk=movement_id)
        existing = SimpleNamespace(
            pk=uuid4(),
            truck_movement_id=movement_id,
            idempotency_key='em-depart-same-key',
            booking_id=None,
            shipment_id=None,
        )
        scoped_qs = MagicMock()
        scoped_qs.first.return_value = existing
        base_qs = MagicMock()
        base_qs.filter.return_value = scoped_qs
        mock_model.objects.filter.return_value = base_qs

        result = ActionExecutionService._find_idempotent_existing(
            idempotency_key='em-depart-same-key',
            source_channel='mobile_driver',
            source_ref=f'movement:{movement_id}:EM2',
            movement=movement,
            job_type='movement',
        )
        self.assertIs(result, existing)
