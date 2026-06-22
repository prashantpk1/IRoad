"""Idempotency scope helpers."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.idempotency import idempotent_log_matches_job_scope


class IdempotencyScopeTests(SimpleTestCase):
    def test_movement_scope_requires_matching_pk(self):
        movement_id = uuid4()
        other_id = uuid4()
        movement = SimpleNamespace(pk=movement_id)
        log = SimpleNamespace(truck_movement_id=other_id)
        self.assertFalse(
            idempotent_log_matches_job_scope(
                log=log,
                job_type='movement',
                movement=movement,
            )
        )
        log_same = SimpleNamespace(truck_movement_id=movement_id)
        self.assertTrue(
            idempotent_log_matches_job_scope(
                log=log_same,
                job_type='movement',
                movement=movement,
            )
        )
