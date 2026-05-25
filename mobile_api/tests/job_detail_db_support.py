"""
Shared PostgreSQL + tenant-schema fixtures for Job Detail DB E2E tests.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from django.db import connection
from django.test import RequestFactory, TransactionTestCase
from django.utils import timezone

from mobile_api.helpers.job_detail_readiness import (
    any_job_detail_ready,
    audit_job_detail_schemas,
)
from mobile_api.helpers.job_execution_security import SecureJobExecutionContext
from mobile_api.helpers.job_list_security import preload_driver_ownership_scope


def job_detail_db_use_dev_database() -> bool:
    """When True, Django test runner reuses the dev DB (see config/settings.py TEST NAME)."""
    return os.environ.get('MOBILE_API_JOB_DETAIL_TEST_USE_DEV_DB', '').strip().lower() in (
        '1',
        'true',
        'yes',
    )


def _connection_is_ephemeral_test_db() -> bool:
    name = (connection.settings_dict.get('NAME') or '').strip()
    return name.startswith('test_')


def job_detail_db_tests_enabled() -> bool:
    """
    Run on PostgreSQL when explicitly enabled or (dev DB + ready tenant schema).

    ``manage.py test`` clones DB to ``test_*`` by default — set
    ``MOBILE_API_JOB_DETAIL_TEST_USE_DEV_DB=1`` so tests hit migrated tenant schemas.
    """
    if connection.vendor != 'postgresql':
        return False
    if os.environ.get('MOBILE_API_SKIP_JOB_DETAIL_DB_TESTS', '').strip().lower() in (
        '1',
        'true',
        'yes',
    ):
        return False
    force = os.environ.get('MOBILE_API_RUN_JOB_DETAIL_DB_TESTS', '').strip().lower() in (
        '1',
        'true',
        'yes',
    )
    if _connection_is_ephemeral_test_db() and not job_detail_db_use_dev_database():
        return False
    if force or job_detail_db_use_dev_database():
        return any_job_detail_ready(audit_job_detail_schemas())
    return any_job_detail_ready(audit_job_detail_schemas())


def pick_job_detail_schema() -> str | None:
    explicit = (os.environ.get('MOBILE_API_JOB_DETAIL_TEST_SCHEMA') or '').strip()
    if explicit:
        return explicit
    for report in audit_job_detail_schemas():
        if report.ready:
            return report.schema
    from mobile_api.helpers.job_list_readiness import list_tenant_schemas

    names = list_tenant_schemas()
    return names[0] if names else None


def skip_reason() -> str:
    if connection.vendor != 'postgresql':
        return 'PostgreSQL required for Job Detail DB E2E tests'
    if os.environ.get('MOBILE_API_SKIP_JOB_DETAIL_DB_TESTS', '').strip().lower() in (
        '1',
        'true',
        'yes',
    ):
        return 'MOBILE_API_SKIP_JOB_DETAIL_DB_TESTS is set'
    if _connection_is_ephemeral_test_db() and not job_detail_db_use_dev_database():
        return (
            'Django test DB (test_*) has no tenant schemas — set '
            'MOBILE_API_JOB_DETAIL_TEST_USE_DEV_DB=1 to reuse dev database'
        )
    schema = pick_job_detail_schema()
    if not schema:
        return 'No tenant schema found'
    reports = audit_job_detail_schemas(schemas=[schema])
    if reports and reports[0].ready:
        return ''
    return (
        f'Schema {schema} not Job Detail READY — '
        'run: python manage.py migrate_job_detail_tenants --apply'
    )


class JobDetailDbTestBase(TransactionTestCase):
    """
    Real tenant schema context; creates isolated driver/shipment/movement rows.

    Uses TransactionTestCase so threaded lock tests and execution commits behave
    like production (no outer test transaction wrapping).
    """

    databases = {'default'}

    @classmethod
    def setUpClass(cls):
        from unittest import SkipTest

        super().setUpClass()
        if not job_detail_db_tests_enabled():
            raise SkipTest(skip_reason() or 'Job Detail DB E2E disabled')
        cls.tenant_schema = pick_job_detail_schema()
        if not cls.tenant_schema:
            raise SkipTest('No tenant schema available')

    def setUp(self):
        from django_tenants.utils import schema_context

        self.factory = RequestFactory()
        self.ctx = schema_context(self.tenant_schema)
        self.ctx.__enter__()
        self._seed()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _fixture_teardown(self):
        """Never flush the shared dev database after real-data E2E tests."""
        if job_detail_db_use_dev_database():
            return
        super()._fixture_teardown()

    def _seed(self):
        from tenant_workspace.models import (
            DriverMaster,
            TenantOperationAction,
            TenantShipment,
            TenantTruckMovementLog,
            TenantUser,
        )

        self.tenant_user = TenantUser.objects.filter(
            status=TenantUser.Status.ACTIVE,
        ).first()
        if self.tenant_user is None:
            suffix = uuid.uuid4().hex[:8]
            self.tenant_user = TenantUser.objects.create(
                username=f'jdtest_{suffix}',
                full_name='JD DB Test',
                email=f'jdtest_{suffix}@test.local',
                password_hash='test-hash',
            )

        self.driver = DriverMaster.objects.filter(
            driver_status=DriverMaster.Status.ACTIVE,
        ).first()
        if self.driver is None:
            self.driver = DriverMaster.objects.create(
                driver_code=f'JD{uuid.uuid4().hex[:6]}',
                driver_status=DriverMaster.Status.ACTIVE,
                driver_source=DriverMaster.DriverSource.IN_SOURCE,
                driver_type=DriverMaster.DriverType.COMPANY,
            )

        self.shipment = self._resolve_executable_shipment()
        self.movement = self._resolve_executable_movement()

        self.actions = list(
            TenantOperationAction.objects.filter(
                status=TenantOperationAction.Status.ACTIVE,
            ).order_by('sequence_number')[:50],
        )

    def _resolve_executable_shipment(self):
        from iroad_tenants.services.operation_execution_service import (
            OperationExecutionService,
        )
        from mobile_api.helpers.job_list_driver_scope import filter_shipments_for_driver
        from tenant_workspace.models import TenantShipment

        terminal = {
            TenantShipment.ShipmentStatus.CANCELLED,
            TenantShipment.ShipmentStatus.CLOSED,
        }
        candidates = (
            filter_shipments_for_driver(self.driver)
            .exclude(shipment_status__in=terminal)
            .order_by('-updated_at')[:100]
        )
        for row in candidates:
            if OperationExecutionService.get_allowed_driver_actions(shipment=row).get(
                'actions'
            ):
                return row
        return TenantShipment.objects.create(
            shipment_id=uuid.uuid4(),
            shipment_no=f'JD-TST-{uuid.uuid4().hex[:8]}',
            booking_item_ref='JD-E2E',
            shipment_status=TenantShipment.ShipmentStatus.LOADED,
            sourcing_mode=TenantShipment.SourcingMode.IN_SOURCE,
            driver=self.driver,
        )

    def _resolve_executable_movement(self):
        from iroad_tenants.services.operation_execution_service import (
            OperationExecutionService,
        )
        from mobile_api.helpers.dashboard_security import movement_queryset_for_driver
        from tenant_workspace.models import TenantTruckMovementLog

        candidates = (
            movement_queryset_for_driver(self.driver)
            .exclude(status=TenantTruckMovementLog.Status.CANCELLED)
            .order_by('-updated_at')[:100]
        )
        for row in candidates:
            if OperationExecutionService.get_allowed_driver_actions(movement=row).get(
                'actions'
            ):
                return row
        return TenantTruckMovementLog.objects.create(
            movement_id=uuid.uuid4(),
            movement_no=f'JD-M-{uuid.uuid4().hex[:8]}',
            movement_source='empty',
            empty_move_reason='Depot',
            status=TenantTruckMovementLog.Status.SCHEDULED,
            driver=self.driver,
        )

    def build_execution_context(self) -> SecureJobExecutionContext:
        scope = preload_driver_ownership_scope(self.driver)
        return SecureJobExecutionContext(
            driver=self.driver,
            tenant_user=self.tenant_user,
            tenant_schema=self.tenant_schema,
            driver_id=str(self.driver.driver_id),
            user_id=str(self.tenant_user.user_id),
            jwt_driver_id=str(self.driver.driver_id),
            ownership_scope=scope,
            jwt_payload={'tenant_schema': self.tenant_schema, 'driver_id': str(self.driver.driver_id)},
        )

    @contextmanager
    def mobile_execution_guard(self, ctx: SecureJobExecutionContext | None = None):
        """Activate internal guard for direct ``ActionExecutionService`` DB tests."""
        from mobile_api.helpers.mobile_execution_guard import mobile_execution_guard

        bound = ctx or self.build_execution_context()
        with mobile_execution_guard(bound):
            yield bound

    def pick_allowed_shipment_action(self):
        from iroad_tenants.services.operation_execution_service import (
            OperationExecutionService,
        )
        from tenant_workspace.models import TenantOperationAction

        payload = OperationExecutionService.get_allowed_driver_actions(
            shipment=self.shipment,
        )
        for item in payload.get('actions') or []:
            if not isinstance(item, dict):
                continue
            aid = item.get('action_id')
            if not aid:
                continue
            action = TenantOperationAction.objects.filter(pk=aid).first()
            if action is not None:
                return action
        return None

    def pick_allowed_movement_action(self):
        from iroad_tenants.services.operation_execution_service import (
            OperationExecutionService,
        )
        from tenant_workspace.models import TenantOperationAction

        payload = OperationExecutionService.get_allowed_driver_actions(
            movement=self.movement,
        )
        for item in payload.get('actions') or []:
            if not isinstance(item, dict):
                continue
            aid = item.get('action_id')
            if not aid:
                continue
            action = TenantOperationAction.objects.filter(pk=aid).first()
            if action is not None:
                return action
        return None

    def make_timeline_request(self, *, cursor: str | None = None, page_size: str = '2'):
        path = (
            f'/api/v1/mobile/driver/jobs/shipments/{self.shipment.shipment_id}/timeline/'
        )
        params = {'page_size': page_size}
        if cursor:
            params['cursor'] = cursor
        request = self.factory.get(path, params)
        request.query_params = request.GET
        return request

    def create_action_logs(
        self,
        *,
        count: int,
        action=None,
        shipment=None,
        movement=None,
        clear_shipment: bool = False,
    ):
        from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
        from tenant_workspace.models import TenantOperationActionLog

        action = action or (self.actions[0] if self.actions else None)
        if action is None:
            return []
        if clear_shipment:
            shipment = None
        elif shipment is not None:
            pass
        else:
            shipment = self.shipment
        base = timezone.now()
        rows = []
        for i in range(count):
            rows.append(
                TenantOperationActionLog.objects.create(
                    log_no=f'JD-TL-{uuid.uuid4().hex[:10]}',
                    log_sequence=i + 1,
                    log_date=base - timedelta(minutes=i),
                    operation_action=action,
                    shipment=shipment,
                    truck_movement=movement,
                    driver=self.driver,
                    source='Mobile',
                    source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                )
            )
        return rows

    def log_count_for_shipment(self) -> int:
        from tenant_workspace.models import TenantOperationActionLog

        return TenantOperationActionLog.objects.filter(
            shipment_id=self.shipment.pk,
            driver_id=self.driver.pk,
        ).count()

    def fresh_shipment_for_concurrency(self):
        """Dedicated shipment row so parallel tests do not share workflow state."""
        from tenant_workspace.models import TenantShipment

        return TenantShipment.objects.create(
            shipment_id=uuid.uuid4(),
            shipment_no=f'JD-CONC-{uuid.uuid4().hex[:8]}',
            booking_item_ref='JD-CONC',
            shipment_status=TenantShipment.ShipmentStatus.LOADED,
            sourcing_mode=TenantShipment.SourcingMode.IN_SOURCE,
            driver=self.driver,
        )

    def pick_allowed_action_for_shipment(self, shipment):
        from iroad_tenants.services.operation_execution_service import (
            OperationExecutionService,
        )
        from tenant_workspace.models import TenantOperationAction

        payload = OperationExecutionService.get_allowed_driver_actions(
            shipment=shipment,
        )
        for item in payload.get('actions') or []:
            if not isinstance(item, dict):
                continue
            aid = item.get('action_id')
            if not aid:
                continue
            action = TenantOperationAction.objects.filter(pk=aid).first()
            if action is not None:
                return action
        return None

    def log_count_for_movement(self) -> int:
        from tenant_workspace.models import TenantOperationActionLog

        return TenantOperationActionLog.objects.filter(
            truck_movement_id=self.movement.pk,
            driver_id=self.driver.pk,
        ).count()

    def media_count_for_shipment_logs(self) -> int:
        from tenant_workspace.models import TenantOperationActionLog, TenantOperationActionMedia

        log_ids = TenantOperationActionLog.objects.filter(
            shipment_id=self.shipment.pk,
        ).values_list('pk', flat=True)
        return TenantOperationActionMedia.objects.filter(action_log_id__in=log_ids).count()

    def timeline_log_count_shipment(self) -> int:
        from iroad_tenants.services.timeline_service import TimelineService

        return TimelineService.scoped_action_log_queryset(
            shipment=self.shipment,
            driver_id=self.driver.pk,
        ).count()


@dataclass
class RollbackSnapshot:
    """Point-in-time counts and status fields for rollback assertions."""

    shipment_status: str
    movement_status: str
    shipment_log_count: int
    movement_log_count: int
    media_count: int
    timeline_count: int
    shipment_updated_at: Any
    movement_updated_at: Any


class JobDetailRollbackTestMixin:
    """
    Helpers for transaction rollback proofs (policy bypass for isolated tenant data).
    """

    def ensure_rollback_test_action(self, *, code_suffix: str | None = None):
        """ACTIVE action with no status impacts — safe for log-only rollback tests."""
        from tenant_workspace.models import TenantOperationAction

        suffix = code_suffix or uuid.uuid4().hex[:8]
        action_code = f'JD-RB-{suffix}'
        action, _ = TenantOperationAction.objects.get_or_create(
            action_code=action_code,
            defaults={
                'english_label': 'Job Detail Rollback Test',
                'status': TenantOperationAction.Status.ACTIVE,
                'sequence_number': 99999,
            },
        )
        if action.status != TenantOperationAction.Status.ACTIVE:
            action.status = TenantOperationAction.Status.ACTIVE
            action.save(update_fields=['status', 'updated_at'])
        return action

    def ensure_status_impact_action(
        self,
        *,
        shipment_impact: str = 'In Transit',
        movement_impact: str = '',
    ):
        from tenant_workspace.models import TenantOperationAction

        suffix = uuid.uuid4().hex[:8]
        return TenantOperationAction.objects.create(
            action_code=f'JD-RB-IMP-{suffix}',
            english_label='Rollback Impact Test',
            status=TenantOperationAction.Status.ACTIVE,
            sequence_number=99998,
            shipment_status_impact=shipment_impact,
            movement_status_impact=movement_impact,
        )

    def capture_rollback_snapshot(self, *, shipment=None, movement=None) -> RollbackSnapshot:
        shipment = shipment or self.shipment
        movement = movement or self.movement
        shipment.refresh_from_db()
        movement.refresh_from_db()
        return RollbackSnapshot(
            shipment_status=shipment.shipment_status,
            movement_status=movement.status,
            shipment_log_count=self.log_count_for_shipment(),
            movement_log_count=self.log_count_for_movement(),
            media_count=self.media_count_for_shipment_logs(),
            timeline_count=self.timeline_log_count_shipment(),
            shipment_updated_at=shipment.updated_at,
            movement_updated_at=movement.updated_at,
        )

    def assert_rollback_snapshot(self, before: RollbackSnapshot, *, msg: str = '') -> None:
        self.shipment.refresh_from_db()
        self.movement.refresh_from_db()
        prefix = f'{msg}: ' if msg else ''
        self.assertEqual(
            self.shipment.shipment_status,
            before.shipment_status,
            f'{prefix}shipment status mutated',
        )
        self.assertEqual(
            self.movement.status,
            before.movement_status,
            f'{prefix}movement status mutated',
        )
        self.assertEqual(
            self.log_count_for_shipment(),
            before.shipment_log_count,
            f'{prefix}shipment action log count changed',
        )
        self.assertEqual(
            self.log_count_for_movement(),
            before.movement_log_count,
            f'{prefix}movement action log count changed',
        )
        self.assertEqual(
            self.media_count_for_shipment_logs(),
            before.media_count,
            f'{prefix}media rows leaked',
        )
        self.assertEqual(
            self.timeline_log_count_shipment(),
            before.timeline_count,
            f'{prefix}timeline row count changed',
        )
        self.assertEqual(
            self.shipment.updated_at,
            before.shipment_updated_at,
            f'{prefix}shipment updated_at changed',
        )
        self.assertEqual(
            self.movement.updated_at,
            before.movement_updated_at,
            f'{prefix}movement updated_at changed',
        )

    @contextmanager
    def bypass_execution_policy(self, *, action):
        """Allow execute paths without Action Master workflow configuration."""
        from iroad_tenants.services.action_execution_service import ActionExecutionService
        from iroad_tenants.services.operation_execution_service import (
            OperationExecutionService,
        )

        def _allowed_payload(*args, **kwargs):
            return OperationExecutionService.get_allowed_driver_actions(
                shipment=kwargs.get('shipment') or self.shipment,
                movement=kwargs.get('movement'),
                include_action_id=action.pk,
            )

        with patch.object(
            OperationExecutionService,
            'validate_driver_action_execution',
            return_value=None,
        ), patch.object(
            ActionExecutionService,
            'validate_driver_action_execution',
            return_value=None,
        ), patch(
            'mobile_api.helpers.job_execution_security.authorize_driver_action_execution',
            return_value={'success': True},
        ), patch(
            'mobile_api.helpers.execution_workflow_cache.get_allowed_driver_actions_cached',
            side_effect=_allowed_payload,
        ):
            yield

    def make_execute_request_with_media(self):
        """Minimal request with JSON media array (no file upload)."""
        request = self.factory.post(
            f'/api/v1/mobile/driver/jobs/shipments/{self.shipment.shipment_id}/actions/execute/',
        )
        request.data = {
            'media': [{'media_type': 'photo', 'description': 'rollback-e2e'}],
        }
        return request
