"""Unit tests for driver empty move creation service."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.empty_move.exceptions import EmptyMoveError
from mobile_api.empty_move.services.empty_move_create_service import (
    EmptyMoveCreateService,
)


def _driver(pk=None):
    pk = pk or uuid4()
    return SimpleNamespace(
        pk=pk,
        driver_id=pk,
        driver_code='DR-0001',
        english_name='Test Driver',
        driver_status='Active',
    )


class EmptyMoveCreateServiceTests(SimpleTestCase):
    @patch('mobile_api.empty_move.services.empty_move_create_service.schema_context')
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.DashboardMovementSelector'
    )
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.DashboardBookingSelector'
    )
    def test_blocks_when_active_booking_job(
        self,
        mock_booking_cls,
        mock_movement_cls,
        _schema,
    ):
        mock_booking_cls.return_value.select_current_driver_booking.return_value = (
            SimpleNamespace(active_shipment=None)
        )
        mock_movement_cls.return_value.select_current_empty_move.return_value = None

        service = EmptyMoveCreateService()
        with self.assertRaises(EmptyMoveError) as ctx:
            service.create_empty_move(
                driver=_driver(),
                tenant_user=SimpleNamespace(pk=uuid4()),
                tenant_schema='tenant_test',
                payload={
                    'empty_move_reason': 'reposition',
                    'from_location_id': uuid4(),
                    'to_location_id': uuid4(),
                },
            )
        self.assertEqual(ctx.exception.code, 'active_job_present')

    @patch('mobile_api.empty_move.services.empty_move_create_service.schema_context')
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.DashboardMovementSelector'
    )
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.DashboardBookingSelector'
    )
    def test_blocks_when_empty_move_already_active(
        self,
        mock_booking_cls,
        mock_movement_cls,
        _schema,
    ):
        mock_booking_cls.return_value.select_current_driver_booking.return_value = None
        mock_movement_cls.return_value.select_current_empty_move.return_value = (
            SimpleNamespace(movement=SimpleNamespace())
        )

        service = EmptyMoveCreateService()
        with self.assertRaises(EmptyMoveError) as ctx:
            service.create_empty_move(
                driver=_driver(),
                tenant_user=SimpleNamespace(pk=uuid4()),
                tenant_schema='tenant_test',
                payload={
                    'empty_move_reason': 'maintenance',
                    'from_location_id': uuid4(),
                    'to_location_id': uuid4(),
                },
            )
        self.assertEqual(ctx.exception.code, 'empty_move_already_active')

    @patch('mobile_api.empty_move.services.empty_move_create_service.transaction')
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.birth_empty_move_for_driver'
    )
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service._resolve_driver_truck'
    )
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service._resolve_location'
    )
    @patch('mobile_api.empty_move.services.empty_move_create_service.schema_context')
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.DashboardMovementSelector'
    )
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.DashboardBookingSelector'
    )
    def test_creates_empty_move_without_auto_start(
        self,
        mock_booking_cls,
        mock_movement_cls,
        _schema,
        mock_resolve_location,
        mock_resolve_truck,
        mock_birth,
        _txn,
    ):
        mock_booking_cls.return_value.select_current_driver_booking.return_value = None
        mock_movement_cls.return_value.select_current_empty_move.return_value = None
        mock_resolve_truck.return_value = SimpleNamespace(pk=uuid4())
        loc = SimpleNamespace(display_label='Loc A')
        mock_resolve_location.side_effect = [loc, loc]

        movement_id = uuid4()
        movement = SimpleNamespace(
            pk=movement_id,
            movement_id=movement_id,
            movement_no='TML-0001',
            status='Scheduled',
            empty_move_reason='reposition',
            from_location_point=loc,
            to_location_point=loc,
        )
        mock_birth.return_value = movement

        with patch(
            'mobile_api.empty_move.services.empty_move_create_service.TenantTruckMovementLog'
        ) as mock_model:
            mock_model.objects.select_related.return_value.get.return_value = movement
            service = EmptyMoveCreateService()
            with patch.object(service, '_auto_start_movement', return_value=False):
                result = service.create_empty_move(
                    driver=_driver(),
                    tenant_user=SimpleNamespace(pk=uuid4()),
                    tenant_schema='tenant_test',
                    payload={
                        'empty_move_reason': 'reposition',
                        'from_location_id': uuid4(),
                        'to_location_id': uuid4(),
                        'auto_start': False,
                    },
                )

        self.assertEqual(result['empty_move']['movement_no'], 'TML-0001')
        self.assertEqual(result['empty_move']['job_type'], 'movement')
        self.assertFalse(result['empty_move']['workflow_started'])
