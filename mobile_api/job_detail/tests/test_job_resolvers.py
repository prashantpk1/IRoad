"""
Resolver layer tests — ownership, tenant isolation, entity lookup (mocked ORM).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.job_detail.dto.job_resolve_context import (
    WORKFLOW_SOURCE_ENTITY_RESOLVER,
)
from mobile_api.job_detail.guards.ownership import (
    driver_owns_shipment_leg,
    movement_is_empty_move_job,
)
from mobile_api.job_detail.services.movement_job_resolver import resolve_empty_move_job
from mobile_api.job_detail.services.shipment_job_resolver import resolve_shipment_job
from tenant_workspace.models import DriverMaster, TenantShipment, TenantTruckMovementLog


def _driver(*, pk=None, active=True):
    d = MagicMock()
    d.pk = pk or uuid4()
    d.driver_id = d.pk
    d.driver_status = (
        DriverMaster.Status.ACTIVE if active else DriverMaster.Status.INACTIVE
    )
    return d


def _booking(*, assigned=None, backload_driver=None):
    b = MagicMock()
    b.pk = uuid4()
    b.assigned_driver_id = assigned
    b.booking_line_backload_driver_id = backload_driver
    return b


def _shipment(
    *,
    driver_id=None,
    booking=None,
    line_type='outbound',
    status=TenantShipment.ShipmentStatus.LOADED,
    shipment_no='SH-100',
):
    s = MagicMock()
    s.pk = uuid4()
    s.shipment_id = s.pk
    s.shipment_no = shipment_no
    s.shipment_status = status
    s.booking_item_type = line_type
    s.driver_id = driver_id
    s.booking = booking
    s.booking_id = getattr(booking, 'pk', None) if booking else None
    return s


def _movement(
    *,
    driver_id=None,
    movement_source='empty',
    empty_move_reason='Depot',
    status=TenantTruckMovementLog.Status.SCHEDULED,
    shipment_id=None,
    movement_no='EM-200',
):
    m = MagicMock()
    m.pk = uuid4()
    m.movement_id = m.pk
    m.movement_no = movement_no
    m.movement_source = movement_source
    m.empty_move_reason = empty_move_reason
    m.status = status
    m.driver_id = driver_id
    m.shipment_id = shipment_id
    return m


def _schema_context_mock(mock_schema):
    mock_schema.return_value.__enter__ = MagicMock(return_value=None)
    mock_schema.return_value.__exit__ = MagicMock(return_value=False)


class OwnershipPolicyTests(SimpleTestCase):
    def test_driver_owns_shipment_via_assigned_driver(self):
        driver = _driver()
        booking = _booking(assigned=driver.pk)
        shipment = _shipment(booking=booking, line_type='outbound')
        self.assertTrue(driver_owns_shipment_leg(driver, booking, shipment))

    def test_driver_owns_backload_via_booking_line_driver(self):
        driver = _driver()
        other = uuid4()
        booking = _booking(assigned=other, backload_driver=driver.pk)
        shipment = _shipment(booking=booking, line_type='backload')
        self.assertTrue(driver_owns_shipment_leg(driver, booking, shipment))

    def test_wrong_driver_does_not_own_leg(self):
        driver = _driver()
        booking = _booking(assigned=uuid4())
        shipment = _shipment(booking=booking)
        self.assertFalse(driver_owns_shipment_leg(driver, booking, shipment))

    def test_empty_move_job_rejects_loaded_shipment_movement(self):
        movement = _movement(movement_source='Loaded', shipment_id=uuid4())
        self.assertFalse(movement_is_empty_move_job(movement))


class ShipmentJobResolverTests(SimpleTestCase):
    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.lookup_shipment_by_reference',
    )
    def test_correct_driver_resolves_shipment(self, mock_lookup, mock_schema):
        _schema_context_mock(mock_schema)
        driver = _driver()
        booking = _booking(assigned=driver.pk)
        shipment = _shipment(booking=booking, driver_id=driver.pk)
        mock_lookup.return_value = shipment

        ctx = resolve_shipment_job(
            driver,
            str(shipment.pk),
            tenant_schema='tenant_a',
        )

        self.assertTrue(ctx.ownership_validated)
        self.assertEqual(ctx.job_type, 'shipment')
        self.assertEqual(ctx.workflow_source, WORKFLOW_SOURCE_ENTITY_RESOLVER)
        self.assertEqual(ctx.entity['shipment_no'], 'SH-100')
        self.assertIs(ctx.entity_row, shipment)
        self.assertIs(ctx.booking, booking)
        self.assertIsNone(ctx.error_code)

    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.lookup_shipment_by_reference',
    )
    def test_wrong_driver_forbidden(self, mock_lookup, mock_schema):
        _schema_context_mock(mock_schema)
        driver = _driver()
        booking = _booking(assigned=uuid4())
        shipment = _shipment(booking=booking)
        mock_lookup.return_value = shipment

        ctx = resolve_shipment_job(
            driver,
            str(shipment.pk),
            tenant_schema='tenant_a',
        )

        self.assertFalse(ctx.ownership_validated)
        self.assertEqual(ctx.error_code, 'forbidden')

    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.lookup_shipment_by_reference',
    )
    def test_missing_tenant_schema(self, mock_lookup):
        driver = _driver()
        ctx = resolve_shipment_job(driver, 'any-id', tenant_schema='')
        self.assertEqual(ctx.error_code, 'tenant_required')
        mock_lookup.assert_not_called()

    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.lookup_shipment_by_reference',
    )
    def test_inactive_cancelled_shipment(self, mock_lookup, mock_schema):
        _schema_context_mock(mock_schema)
        driver = _driver()
        booking = _booking(assigned=driver.pk)
        shipment = _shipment(
            booking=booking,
            driver_id=driver.pk,
            status=TenantShipment.ShipmentStatus.CANCELLED,
        )
        mock_lookup.return_value = shipment

        ctx = resolve_shipment_job(
            driver,
            shipment.shipment_no,
            tenant_schema='tenant_a',
        )

        self.assertFalse(ctx.ownership_validated)
        self.assertEqual(ctx.error_code, 'job_inactive')

    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.lookup_shipment_by_reference',
    )
    def test_schema_context_uses_jwt_tenant(self, mock_lookup, mock_schema_ctx):
        driver = _driver()
        booking = _booking(assigned=driver.pk)
        shipment = _shipment(booking=booking, driver_id=driver.pk)
        mock_lookup.return_value = shipment
        mock_schema_ctx.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema_ctx.return_value.__exit__ = MagicMock(return_value=False)

        resolve_shipment_job(driver, str(shipment.pk), tenant_schema='tenant_xyz')

        mock_schema_ctx.assert_called_once_with('tenant_xyz')
        mock_lookup.assert_called_once()

    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.lookup_shipment_by_reference',
    )
    def test_shipment_not_found(self, mock_lookup, mock_schema):
        _schema_context_mock(mock_schema)
        mock_lookup.return_value = None
        ctx = resolve_shipment_job(_driver(), 'missing', tenant_schema='tenant_a')
        self.assertEqual(ctx.error_code, 'job_not_found')


class MovementJobResolverTests(SimpleTestCase):
    @patch(
        'mobile_api.job_detail.services.movement_job_resolver.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.movement_job_resolver.lookup_movement_by_reference',
    )
    def test_correct_driver_resolves_empty_move(self, mock_lookup, mock_schema):
        _schema_context_mock(mock_schema)
        driver = _driver()
        movement = _movement(driver_id=driver.pk)
        mock_lookup.return_value = movement

        ctx = resolve_empty_move_job(
            driver,
            movement.movement_no,
            tenant_schema='tenant_a',
        )

        self.assertTrue(ctx.ownership_validated)
        self.assertEqual(ctx.job_type, 'movement')
        self.assertEqual(ctx.entity['movement_no'], 'EM-200')
        self.assertIs(ctx.entity_row, movement)

    @patch(
        'mobile_api.job_detail.services.movement_job_resolver.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.movement_job_resolver.lookup_movement_by_reference',
    )
    def test_wrong_driver_forbidden(self, mock_lookup, mock_schema):
        _schema_context_mock(mock_schema)
        driver = _driver()
        movement = _movement(driver_id=uuid4())
        mock_lookup.return_value = movement

        ctx = resolve_empty_move_job(
            driver,
            str(movement.pk),
            tenant_schema='tenant_a',
        )

        self.assertFalse(ctx.ownership_validated)
        self.assertEqual(ctx.error_code, 'forbidden')

    @patch(
        'mobile_api.job_detail.services.movement_job_resolver.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.movement_job_resolver.lookup_movement_by_reference',
    )
    def test_laden_movement_not_empty_move_job(self, mock_lookup, mock_schema):
        _schema_context_mock(mock_schema)
        driver = _driver()
        movement = _movement(
            driver_id=driver.pk,
            movement_source='Loaded',
            shipment_id=uuid4(),
            empty_move_reason='',
        )
        mock_lookup.return_value = movement

        ctx = resolve_empty_move_job(
            driver,
            str(movement.pk),
            tenant_schema='tenant_a',
        )

        self.assertEqual(ctx.error_code, 'not_empty_move')

    @patch(
        'mobile_api.job_detail.services.movement_job_resolver.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.movement_job_resolver.lookup_movement_by_reference',
    )
    def test_cancelled_movement_inactive(self, mock_lookup, mock_schema):
        _schema_context_mock(mock_schema)
        driver = _driver()
        movement = _movement(
            driver_id=driver.pk,
            status=TenantTruckMovementLog.Status.CANCELLED,
        )
        mock_lookup.return_value = movement

        ctx = resolve_empty_move_job(
            driver,
            str(movement.pk),
            tenant_schema='tenant_a',
        )

        self.assertEqual(ctx.error_code, 'job_inactive')

    def test_inactive_driver_rejected(self):
        ctx = resolve_empty_move_job(
            _driver(active=False),
            'em-1',
            tenant_schema='tenant_a',
        )
        self.assertEqual(ctx.error_code, 'driver_inactive')
