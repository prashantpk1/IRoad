"""Unit tests for driver empty move creation service."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
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
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.is_active_empty_move',
        return_value=True,
    )
    def test_blocks_when_empty_move_already_active(
        self,
        _mock_active,
        mock_booking_cls,
        mock_movement_cls,
        _schema,
    ):
        mock_booking_cls.return_value.select_current_driver_booking.return_value = None
        movement = SimpleNamespace(
            pk=uuid4(),
            movement_id=uuid4(),
            movement_no='EM-EXISTING',
            status='Scheduled',
            empty_move_reason='maintenance',
        )
        mock_movement_cls.return_value.select_current_empty_move.return_value = (
            SimpleNamespace(movement=movement, movement_stage='created')
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
        self.assertTrue(ctx.exception.data.get('resume_existing'))
        self.assertEqual(
            (ctx.exception.data.get('resume_job') or {}).get('job_no'),
            'EM-EXISTING',
        )

    @patch('mobile_api.empty_move.services.empty_move_create_service.schema_context')
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.DashboardMovementSelector'
    )
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.DashboardBookingSelector'
    )
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.is_active_empty_move',
        return_value=False,
    )
    def test_allows_create_when_only_closed_empty_move_in_selector(
        self,
        _mock_active,
        mock_booking_cls,
        mock_movement_cls,
        mock_schema,
    ):
        """After End Job, selector may still return a row but it must not block create."""
        mock_booking_cls.return_value.select_current_driver_booking.return_value = None
        closed = SimpleNamespace(
            pk=uuid4(),
            movement_id=uuid4(),
            movement_no='EM-CLOSED',
            status='Completed',
            empty_move_reason='maintenance',
        )
        mock_movement_cls.return_value.select_current_empty_move.return_value = (
            SimpleNamespace(movement=closed, movement_stage='completed')
        )
        mock_schema.return_value.__enter__ = lambda s: None
        mock_schema.return_value.__exit__ = lambda s, *a: None

        service = EmptyMoveCreateService()
        with patch.object(
            service,
            'create_empty_move',
            wraps=service.create_empty_move,
        ):
            with patch(
                'mobile_api.empty_move.services.empty_move_create_service._resolve_driver_truck',
                return_value=None,
            ):
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
        self.assertEqual(ctx.exception.code, 'truck_required')

    @patch('mobile_api.empty_move.services.empty_move_create_service.transaction')
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.apply_movement_route_map_links'
    )
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
    def test_does_not_auto_start_em1_on_create(
        self,
        mock_booking_cls,
        mock_movement_cls,
        _schema,
        mock_resolve_location,
        mock_resolve_truck,
        mock_birth,
        mock_apply_links,
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
            status='In Progress',
            empty_move_reason='reposition',
            from_location_point=loc,
            to_location_point=loc,
            refresh_from_db=MagicMock(),
        )
        mock_birth.return_value = movement

        with patch(
            'mobile_api.empty_move.services.empty_move_create_service.TenantTruckMovementLog'
        ) as mock_model:
            mock_model.objects.select_related.return_value.get.return_value = movement
            service = EmptyMoveCreateService()
            with patch.object(service, '_auto_start_movement', return_value=True) as mock_start:
                result = service.create_empty_move(
                    driver=_driver(),
                    tenant_user=SimpleNamespace(pk=uuid4()),
                    tenant_schema='tenant_test',
                    payload={
                        'empty_move_reason': 'reposition',
                        'from_location_id': uuid4(),
                        'to_location_id': uuid4(),
                    },
                )

        mock_start.assert_not_called()
        self.assertFalse(result['empty_move']['workflow_started'])
        mock_apply_links.assert_called_once()

    @patch('mobile_api.empty_move.services.empty_move_create_service.transaction')
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.apply_movement_route_map_links'
    )
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
    def test_create_applies_departure_gps_only(
        self,
        mock_booking_cls,
        mock_movement_cls,
        _schema,
        mock_resolve_location,
        mock_resolve_truck,
        mock_birth,
        mock_apply_links,
        _txn,
    ):
        mock_booking_cls.return_value.select_current_driver_booking.return_value = None
        mock_movement_cls.return_value.select_current_empty_move.return_value = None
        mock_resolve_truck.return_value = SimpleNamespace(pk=uuid4())
        loc_from = SimpleNamespace(display_label='Depot A')
        loc_to = SimpleNamespace(display_label='Depot B')
        mock_resolve_location.side_effect = [loc_from, loc_to]

        movement_id = uuid4()
        movement = SimpleNamespace(
            pk=movement_id,
            movement_id=movement_id,
            movement_no='TML-0061',
            status='In Progress',
            empty_move_reason='reposition',
            from_location_point=loc_from,
            to_location_point=loc_to,
            refresh_from_db=MagicMock(),
        )
        mock_birth.return_value = movement

        with patch(
            'mobile_api.empty_move.services.empty_move_create_service.TenantTruckMovementLog'
        ) as mock_model:
            mock_model.objects.select_related.return_value.get.return_value = movement
            service = EmptyMoveCreateService()
            result = service.create_empty_move(
                driver=_driver(),
                tenant_user=SimpleNamespace(pk=uuid4()),
                tenant_schema='tenant_test',
                payload={
                    'empty_move_reason': 'reposition',
                    'latitude': 24.7136,
                    'longitude': 46.6753,
                    'from_address': 'Depot A',
                },
            )

        mock_apply_links.assert_called_once()
        link_kwargs = mock_apply_links.call_args.kwargs
        self.assertEqual(link_kwargs['from_latitude'], '24.7136')
        self.assertEqual(link_kwargs['from_longitude'], '46.6753')
        self.assertEqual(link_kwargs['from_address'], 'Depot A')
        self.assertEqual(link_kwargs['to_latitude'], '')
        self.assertEqual(link_kwargs['to_longitude'], '')
        self.assertFalse(result['empty_move']['workflow_started'])
        self.assertFalse(result['workflow_contract']['manual_location_picker'])

    @patch('mobile_api.empty_move.services.empty_move_create_service.transaction')
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.apply_movement_route_map_links'
    )
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.birth_empty_move_for_driver'
    )
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service._resolve_driver_truck'
    )
    @patch('mobile_api.empty_move.services.empty_move_create_service.schema_context')
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.DashboardMovementSelector'
    )
    @patch(
        'mobile_api.empty_move.services.empty_move_create_service.DashboardBookingSelector'
    )
    def test_create_with_gps_only_skips_location_master(
        self,
        mock_booking_cls,
        mock_movement_cls,
        _schema,
        mock_resolve_truck,
        mock_birth,
        mock_apply_links,
        _txn,
    ):
        mock_booking_cls.return_value.select_current_driver_booking.return_value = None
        mock_movement_cls.return_value.select_current_empty_move.return_value = None
        mock_resolve_truck.return_value = SimpleNamespace(pk=uuid4())

        movement_id = uuid4()
        movement = SimpleNamespace(
            pk=movement_id,
            movement_id=movement_id,
            movement_no='TML-0100',
            status='In Progress',
            empty_move_reason='reposition',
            from_location_point=None,
            to_location_point=None,
            from_location_map_link='https://maps.google.com/?q=21.5433,39.1728',
            to_location_map_link='',
            from_location_address='King Abdulaziz Rd, Jeddah',
            to_location_address='',
            from_latitude='21.5433',
            from_longitude='39.1728',
            to_latitude='',
            to_longitude='',
            refresh_from_db=MagicMock(),
        )
        mock_birth.return_value = movement

        with patch(
            'mobile_api.empty_move.services.empty_move_create_service.TenantTruckMovementLog'
        ) as mock_model:
            mock_model.objects.select_related.return_value.get.return_value = movement
            service = EmptyMoveCreateService()
            with patch.object(service, '_auto_start_movement', return_value=True):
                result = service.create_empty_move(
                    driver=_driver(),
                    tenant_user=SimpleNamespace(pk=uuid4()),
                    tenant_schema='tenant_test',
                    payload={
                        'empty_move_reason': 'reposition',
                        'latitude': 21.5433,
                        'longitude': 39.1728,
                        'from_address': 'King Abdulaziz Rd, Jeddah',
                    },
                )

        mock_birth.assert_called_once()
        birth_kwargs = mock_birth.call_args.kwargs
        self.assertIsNone(birth_kwargs['from_location'])
        self.assertIsNone(birth_kwargs['to_location'])
        link_kwargs = mock_apply_links.call_args.kwargs
        self.assertEqual(link_kwargs['from_address'], 'King Abdulaziz Rd, Jeddah')
        self.assertEqual(link_kwargs['to_latitude'], '')
        self.assertEqual(link_kwargs['to_longitude'], '')
        self.assertEqual(
            result['empty_move']['from_location']['display_name'],
            'King Abdulaziz Rd, Jeddah',
        )
        self.assertEqual(
            result['empty_move']['from_location']['from_address'],
            'King Abdulaziz Rd, Jeddah',
        )
        self.assertEqual(result['empty_move']['from_location']['latitude'], '21.5433')
        self.assertEqual(result['empty_move']['from_location']['longitude'], '39.1728')
        to_location = result['empty_move']['to_location']
        self.assertEqual(to_location['latitude'], '')
        self.assertEqual(to_location['longitude'], '')
        self.assertEqual(to_location['location_capture_mode'], 'gps')
        self.assertTrue(to_location['gps_capture_required'])
