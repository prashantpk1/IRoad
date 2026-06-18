"""Auto-shipment line resolution inherits per-leg POD doc count from booking."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from tenant_workspace.models import TenantShipment

from iroad_tenants.operation_runtime.auto_shipment_line import (
    resolve_auto_shipment_target_line,
)


def _closed_outbound():
    return SimpleNamespace(
        pk=uuid4(),
        shipment_status=TenantShipment.ShipmentStatus.CLOSED,
        booking_item_type='Outbound',
        shipment_sequence=1,
        shipment_no='SH-0051',
    )


class AutoShipmentLineResolverTests(TestCase):
    def test_backload_line_selected_when_outbound_closed_and_hint_empty(self):
        booking = SimpleNamespace(
            booking_id=uuid4(),
            trip_type='Round',
            pod_type='Hard',
            booking_line_pod_doc_count=1,
            booking_line_backload_pod_doc_count=2,
            shipments=SimpleNamespace(all=lambda: [_closed_outbound()]),
        )
        backload_line = {
            'booking_item_type': 'Backload',
            'pod_doc_count': 2,
            'pod_type': 'Hard',
        }
        outbound_line = {
            'booking_item_type': 'Outbound',
            'pod_doc_count': 1,
            'pod_type': 'Hard',
        }
        with patch(
            'iroad_tenants.operation_runtime.auto_shipment_line.resolve_preshipment_booking_item_type',
            return_value='Backload',
        ), patch(
            'iroad_tenants.views._tenant_shipment_booking_line_rows',
            return_value=[outbound_line, backload_line],
        ), patch(
            'iroad_tenants.views._tenant_shipment_match_booking_line',
            side_effect=lambda b, **kw: backload_line
            if kw.get('booking_item_type') == 'Backload'
            else None,
        ), patch(
            'iroad_tenants.views._tenant_shipment_line_has_existing_shipment',
            side_effect=lambda b, line_type, **kw: line_type == 'Outbound',
        ):
            line = resolve_auto_shipment_target_line(booking, booking_item_type_hint='')
        self.assertEqual(line['booking_item_type'], 'Backload')
        self.assertEqual(line['pod_doc_count'], 2)

    def test_explicit_backload_hint_wins_over_outbound_fallback(self):
        booking = SimpleNamespace(booking_id=uuid4(), trip_type='Round')
        backload_line = {
            'booking_item_type': 'Backload',
            'pod_doc_count': 2,
            'pod_type': 'Hard',
        }
        with patch(
            'iroad_tenants.views._tenant_shipment_match_booking_line',
            return_value=backload_line,
        ), patch(
            'iroad_tenants.views._tenant_shipment_line_has_existing_shipment',
            return_value=False,
        ):
            line = resolve_auto_shipment_target_line(
                booking,
                booking_item_type_hint='Backload',
            )
        self.assertEqual(line['pod_doc_count'], 2)

    def test_outbound_line_blocked_when_closed_shipment_exists(self):
        booking = SimpleNamespace(
            booking_id=uuid4(),
            trip_type='Round',
            shipments=SimpleNamespace(all=lambda: [_closed_outbound()]),
        )
        outbound_line = {
            'booking_item_type': 'Outbound',
            'pod_doc_count': 1,
        }
        backload_line = {
            'booking_item_type': 'Backload',
            'pod_doc_count': 2,
        }
        with patch(
            'iroad_tenants.operation_runtime.auto_shipment_line.resolve_preshipment_booking_item_type',
            return_value='',
        ), patch(
            'iroad_tenants.views._tenant_shipment_booking_line_rows',
            return_value=[outbound_line, backload_line],
        ), patch(
            'iroad_tenants.views._tenant_shipment_line_has_existing_shipment',
            side_effect=lambda b, line_type, **kw: line_type == 'Outbound',
        ):
            line = resolve_auto_shipment_target_line(booking, booking_item_type_hint='')
        self.assertEqual(line['booking_item_type'], 'Backload')

    def test_outbound_hint_when_backload_not_pending(self):
        booking = SimpleNamespace(booking_id=uuid4(), trip_type='One Way')
        outbound_line = {
            'booking_item_type': 'Outbound',
            'pod_doc_count': 1,
            'pod_type': 'Soft',
        }
        with patch(
            'iroad_tenants.views._tenant_shipment_match_booking_line',
            return_value=outbound_line,
        ), patch(
            'iroad_tenants.views._tenant_shipment_line_has_existing_shipment',
            return_value=False,
        ):
            line = resolve_auto_shipment_target_line(
                booking,
                booking_item_type_hint='Outbound',
            )
        self.assertEqual(line['booking_item_type'], 'Outbound')
        self.assertEqual(line['pod_doc_count'], 1)
