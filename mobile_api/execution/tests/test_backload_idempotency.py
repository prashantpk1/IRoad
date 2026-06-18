"""Idempotency must not replay outbound A1 when executing backload A1."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.guards.execution_idempotency_guard import (
    ExecutionIdempotencyGuard,
    IdempotencyKeys,
)


def _driver():
    return SimpleNamespace(pk=1, driver_id=1, driver_status='Active')


class BackloadIdempotencyGuardTests(TestCase):
    def test_outbound_a1_log_does_not_replay_for_backload_execute(self):
        outbound_log = SimpleNamespace(
            log_id=uuid4(),
            pk=uuid4(),
            operation_action=SimpleNamespace(action_code='A1'),
        )
        booking = SimpleNamespace(
            booking_id=uuid4(),
            pk=uuid4(),
            trip_type='Round',
            shipments=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        pk=uuid4(),
                        shipment_status='Closed',
                        booking_item_type='Outbound',
                        shipment_sequence=1,
                        updated_at=datetime(2026, 6, 17, 18, 0, tzinfo=timezone.utc),
                    ),
                ],
            ),
        )
        ctx = ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='booking',
            job_id=str(booking.pk),
            action_code='A1',
            payload={'client_action_id': 'same-client-key'},
            booking=booking,
        )
        guard = ExecutionIdempotencyGuard(
            log_lookup=lambda _keys: outbound_log,
        )
        with patch(
            'iroad_tenants.operation_runtime.booking_preshipment_cycle.booking_preshipment_log_in_cycle',
            return_value=False,
        ):
            replay = guard.detect_idempotent_replay(
                ctx,
                IdempotencyKeys(
                    idempotency_key='same-client-key',
                    source_ref='booking:1:Backload:A1',
                ),
            )
        self.assertFalse(replay)
        self.assertIsNone(ctx.action_log)

    def test_source_ref_includes_backload_leg(self):
        booking = SimpleNamespace(
            trip_type='Round',
            shipments=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        shipment_status='Closed',
                        booking_item_type='Outbound',
                    ),
                ],
            ),
        )
        ctx = ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='booking',
            job_id='bk-1',
            action_code='A1',
            payload={},
            booking=booking,
        )
        ref = ExecutionIdempotencyGuard._default_source_ref(ctx)
        self.assertIn('Backload', ref)
        self.assertIn('A1', ref)
