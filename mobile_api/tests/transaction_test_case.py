"""
PostgreSQL-safe TransactionTestCase for mobile_api integration tests.

Django only passes ``allow_cascade`` to ``flush`` when ``available_apps`` is set.
Without CASCADE, teardown fails when ``mobile_hard_pod_receipt`` references
``mobile_pod_capture_bundle``.
"""
from __future__ import annotations

from django.core.management import call_command
from django.db import connections
from django.test import TransactionTestCase as DjangoTransactionTestCase


class TransactionTestCase(DjangoTransactionTestCase):
    def _fixture_teardown(self) -> None:
        for db_name in self._databases_names(include_mirrors=False):
            inhibit_post_migrate = (
                self.available_apps is not None
                or (
                    self.serialized_rollback
                    and hasattr(connections[db_name], '_test_serialized_contents')
                )
            )
            call_command(
                'flush',
                verbosity=0,
                interactive=False,
                database=db_name,
                reset_sequences=False,
                allow_cascade=True,
                inhibit_post_migrate=inhibit_post_migrate,
            )
