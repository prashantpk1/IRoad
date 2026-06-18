"""Job detail redirects closed outbound shipment to booking backload bootstrap."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from mobile_api.job_detail.services.job_detail_context_service import (
    JobDetailContextService,
)
from tenant_workspace.models import TenantShipment


def _driver():
    return SimpleNamespace(pk=2, driver_id=2, driver_status='Active')


def _booking():
    b = MagicMock()
    b.booking_id = 'bk-42'
    b.pk = 'bk-42'
    b.booking_no = 'BK-0042'
    b.trip_type = 'Round'
    b.assigned_driver_id = 2
    b.booking_line_backload_driver_id = 2
    b.booking_status = 'Confirmed'
    outbound = MagicMock()
    outbound.pk = 'sh-51'
    outbound.shipment_id = 'sh-51'
    outbound.shipment_no = 'SH-0051'
    outbound.booking_item_type = 'Outbound'
    outbound.shipment_status = TenantShipment.ShipmentStatus.CLOSED
    outbound.booking = b
    b.shipments.all.return_value = [outbound]
    return b, outbound


class JobDetailBackloadRedirectTests(TestCase):
    @patch(
        'mobile_api.job_detail.services.job_detail_context_service.load_projection_cache',
    )
    @patch(
        'mobile_api.job_detail.services.job_detail_context_service.reconcile_job_detail_entities',
    )
    def test_closed_outbound_shipment_pivots_to_booking_job(
        self,
        _reconcile,
        _cache,
    ):
        driver = _driver()
        booking, outbound = _booking()
        resolve_ctx = MagicMock()
        resolve_ctx.ok = True
        resolve_ctx.to_resolver_meta.return_value = {'entity': {}}

        shipment_resolver = MagicMock()
        shipment_resolver.resolve.return_value = MagicMock(
            shipment=outbound,
            booking=booking,
            resolve_context=resolve_ctx,
            error_code=None,
            error_message=None,
        )

        svc = JobDetailContextService(shipment_resolver=shipment_resolver)
        with patch.object(svc, '_projection_service') as proj:
            proj.build.return_value = {}
            context = svc.resolve_job_detail_context(
                driver,
                job_type='shipment',
                job_id='SH-0051',
                tenant_schema='tenant_test',
            )

        self.assertEqual(context.job_type, 'booking')
        self.assertEqual(context.job_id, 'bk-42')
        self.assertIsNone(context.shipment)
        self.assertTrue(context.resolver_meta.get('backload_booking_redirect'))
