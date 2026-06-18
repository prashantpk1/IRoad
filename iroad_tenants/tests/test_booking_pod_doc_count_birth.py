"""Booking line POD doc count must copy to auto-born shipments."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from tenant_workspace.models import TenantBooking, TenantShipment

from iroad_tenants.views import (
    _tenant_booking_line_pod_doc_count,
    _tenant_booking_line_stored_pod_doc_count,
    _tenant_shipment_birth_from_booking_line,
)


def _booking(**kwargs):
    b = SimpleNamespace(
        booking_id=uuid4(),
        booking_no='BK-900',
        booking_status=TenantBooking.Status.CONFIRMED,
        trip_type='Round',
        order_type='Credit',
        pod_type=TenantShipment.PodType.HARD,
        pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        booking_line_pod_doc_count=2,
        booking_line_backload_pod_doc_count=2,
        booking_line_cod_amount=Decimal('200'),
        booking_line_backload_cod_amount=Decimal('2300'),
        cargo_id=uuid4(),
        cargo_qty=Decimal('10'),
        cargo_weight=Decimal('100'),
        cargo_unit='Ton',
        cargo_booking_item='Outbound',
        loading_address_id=uuid4(),
        delivery_address_id=uuid4(),
        price_list=None,
        service_item=None,
        client_account=SimpleNamespace(account_id=uuid4()),
    )
    for key, value in kwargs.items():
        setattr(b, key, value)
    return b


class BookingPodDocCountTests(SimpleTestCase):
    def test_stored_count_wins_over_empty_shipment_for_display(self):
        booking = _booking()
        shipment = SimpleNamespace(pod_doc_count=0)
        self.assertEqual(
            _tenant_booking_line_pod_doc_count(
                booking,
                'Outbound',
                shipment=shipment,
            ),
            2,
        )

    def test_auto_birth_uses_booking_line_pod_doc_count(self):
        booking = _booking()
        matched_line = {
            'booking_item': 'SV-1',
            'booking_item_type': 'Outbound',
            'route_display': 'jeddah To Makkah',
            'order_type': 'Credit',
            'sourcing_mode': TenantShipment.SourcingMode.IN_SOURCE,
            'loading_address_id': booking.loading_address_id,
            'delivery_address_id': booking.delivery_address_id,
            'cargo_id': booking.cargo_id,
            'cod_amount': 0,
            'pod_type': TenantShipment.PodType.HARD,
            'pod_doc_count': 0,
            'truck': SimpleNamespace(status='Active'),
            'driver': SimpleNamespace(driver_status='Active'),
            'cargo_qty': booking.cargo_qty,
            'cargo_weight': booking.cargo_weight,
            'cargo_unit': booking.cargo_unit,
        }
        created = SimpleNamespace(pod_doc_count=0)

        def _capture_shipment(**kwargs):
            nonlocal created
            created = SimpleNamespace(**kwargs)
            created.full_clean = MagicMock()
            created.save = MagicMock()
            return created

        with patch(
            'iroad_tenants.views._tenant_shipment_validate_submission',
            return_value=({}, 'Credit'),
        ), patch(
            'iroad_tenants.views._next_auto_number_for_form',
            return_value=('SH-900', 1),
        ), patch(
            'iroad_tenants.views.TenantShipment',
            side_effect=_capture_shipment,
        ), patch(
            'iroad_tenants.views._tenant_shipment_apply_foreign_keys',
        ), patch(
            'iroad_tenants.views._tenant_shipment_apply_booking_line_to_form',
        ), patch(
            'iroad_tenants.views.TenantAddressMaster',
        ), patch(
            'iroad_tenants.views.TenantCargoMaster',
        ), patch(
            'iroad_tenants.views._tenant_booking_sync_pod_doc_counts_to_shipments',
        ), patch(
            'iroad_tenants.operation_runtime.pod_action._birth_delivery_note_scaffold',
        ):
            _tenant_shipment_birth_from_booking_line(booking, matched_line)

        self.assertEqual(created.pod_doc_count, 2)

    def test_backload_stored_count(self):
        booking = _booking()
        self.assertEqual(
            _tenant_booking_line_stored_pod_doc_count(booking, 'Backload'),
            2,
        )
