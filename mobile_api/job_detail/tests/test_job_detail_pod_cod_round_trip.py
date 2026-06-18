"""
POD/COD and round-trip projection tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase, TestCase

from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
from mobile_api.dashboard.selectors import pod_cod_policy
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.projections.pod_cod_projection import build_pod_cod_section
from mobile_api.job_detail.projections.round_trip_projection import (
    build_round_trip_section,
)
from mobile_api.job_detail.services.job_detail_pod_cod_reconciler import (
    reconcile_job_detail_pod_cod,
)
from tenant_workspace.models import TenantBooking, TenantShipment


def _driver(pk=None):
    d = MagicMock()
    d.pk = pk or uuid4()
    return d


def _booking(*, assigned=None, backload=None, trip='Round'):
    b = MagicMock()
    b.pk = uuid4()
    b.booking_id = b.pk
    b.booking_no = 'BK-100'
    b.trip_type = trip
    b.assigned_driver_id = assigned
    b.booking_line_backload_driver_id = backload
    return b


def _shipment(
    *,
    line='Outbound',
    status=TenantShipment.ShipmentStatus.LOADED,
    pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
    pod_type=TenantShipment.PodType.DIGITAL,
    order_type='',
    collection_status=TenantShipment.CollectionStatus.PENDING,
    driver_id=None,
    pk=None,
):
    s = MagicMock()
    s.pk = pk or uuid4()
    s.shipment_id = s.pk
    s.shipment_no = f'SH-{str(s.pk)[:4]}'
    s.booking_item_type = line
    s.shipment_status = status
    s.pod_status = pod_status
    s.pod_type = pod_type
    s.order_type = order_type
    s.collection_status = collection_status
    s.driver_id = driver_id
    return s


class PodCodProjectionTests(TestCase):
    def test_pod_compliant_from_columns(self):
        shipment = _shipment(
            pod_status=TenantShipment.PodStatus.COMPLETED,
            status=TenantShipment.ShipmentStatus.DELIVERED,
        )
        flags = pod_cod_policy.derive_pod_cod_flags(shipment)
        self.assertTrue(flags['pod_compliant'])
        self.assertFalse(flags['pod_pending'])

    def test_cod_collected(self):
        shipment = _shipment(
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.COLLECTED,
        )
        # Avoid MagicMock auto-attr ``driver`` triggering treasury ORM lookup.
        shipment.driver = None
        flags = pod_cod_policy.derive_pod_cod_flags(shipment)
        self.assertTrue(flags['cod_collected'])
        self.assertFalse(flags['cod_pending'])

    def test_hard_pod_pending(self):
        shipment = _shipment(
            pod_type=TenantShipment.PodType.HARD,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
            status=TenantShipment.ShipmentStatus.AT_DELIVERY,
        )
        self.assertTrue(pod_cod_policy.derive_hard_pod_pending(shipment))

    @patch('mobile_api.job_detail.services.job_detail_pod_cod_reconciler.get_projection_cache')
    def test_reconcile_log_evidence_pod_uploaded(self, mock_cache):
        action = MagicMock(spec=['action_code', 'english_label', 'auto_pod_post', 'hard_copy_collection', 'shipment_status_impact', 'movement_status_impact'])
        action.action_code = 'A7'
        action.english_label = 'Upload POD'
        action.auto_pod_post = False
        action.hard_copy_collection = False
        action.shipment_status_impact = ''
        action.movement_status_impact = ''
        log = MagicMock()
        log.operation_action = action
        cache = MagicMock()
        cache.shipment_logs = [log]
        mock_cache.return_value = cache

        shipment = _shipment(pod_status=TenantShipment.PodStatus.NOT_COMPLETED)
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
            projection_cache=cache,
        )
        bundle = reconcile_job_detail_pod_cod(ctx)
        self.assertTrue(bundle['log_evidence']['pod_uploaded'])

    @patch('mobile_api.job_detail.projections.pod_cod_projection.reconcile_job_detail_pod_cod')
    def test_build_pod_cod_section_uses_reconciliation(self, mock_reconcile):
        mock_reconcile.return_value = {
            'flags': {
                'pod_pending': False,
                'pod_compliant': True,
                'hard_pod_pending': False,
                'cod_pending': False,
                'cod_collected': False,
                'treasury_pending': False,
                'delivery_blocked': False,
            },
            'log_evidence': {'pod_uploaded': True},
            'compliance_integrity': {
                'authority_source': 'action_logs',
                'log_count': 1,
                'compliance_drift': False,
            },
        }
        shipment = _shipment()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
            reconciliation={'pod_cod': mock_reconcile.return_value},
        )
        section = build_pod_cod_section(ctx)
        self.assertTrue(section['pod_compliant'])
        mock_reconcile.assert_not_called()


class RoundTripProjectionTests(SimpleTestCase):
    def test_outbound_delivered_stage_partial(self):
        driver = _driver()
        booking = _booking(assigned=driver.pk, backload=driver.pk)
        outbound = _shipment(
            line='Outbound',
            status=TenantShipment.ShipmentStatus.DELIVERED,
            driver_id=driver.pk,
        )
        backload = _shipment(
            line='Backload',
            status=TenantShipment.ShipmentStatus.LOADED,
            driver_id=driver.pk,
        )
        booking.shipments = MagicMock()
        booking.shipments.all.return_value = [outbound, backload]

        ctx = JobDetailContext(
            driver=driver,
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(outbound.pk),
            shipment=outbound,
            booking=booking,
        )
        section = build_round_trip_section(ctx)

        self.assertEqual(section['booking_execution_stage'], booking_policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED)
        self.assertTrue(section['outbound_progression']['all_execution_complete'])
        self.assertEqual(section['progression_mode'], 'same_driver')
        self.assertEqual(section['next_executable_leg']['booking_item_type'], 'Backload')

    def test_backload_active_stage(self):
        driver = _driver()
        booking = _booking(assigned=driver.pk, backload=driver.pk)
        outbound = _shipment(
            line='Outbound',
            status=TenantShipment.ShipmentStatus.DELIVERED,
            driver_id=driver.pk,
        )
        backload = _shipment(
            line='Backload',
            status=TenantShipment.ShipmentStatus.IN_TRANSIT,
            driver_id=driver.pk,
        )
        booking.shipments = MagicMock()
        booking.shipments.all.return_value = [outbound, backload]

        ctx = JobDetailContext(
            driver=driver,
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(backload.pk),
            shipment=backload,
            booking=booking,
        )
        section = build_round_trip_section(ctx)

        self.assertEqual(
            section['booking_execution_stage'],
            booking_policy.BOOKING_EXECUTION_STAGE_BACKLOAD_ACTIVE,
        )
        self.assertFalse(section['backload_progression']['all_execution_complete'])

    def test_split_driver_booking(self):
        driver_a = _driver()
        driver_b = _driver()
        booking = _booking(assigned=driver_a.pk, backload=driver_b.pk)
        outbound = _shipment(
            line='Outbound',
            status=TenantShipment.ShipmentStatus.DELIVERED,
            driver_id=driver_a.pk,
        )
        backload = _shipment(
            line='Backload',
            status=TenantShipment.ShipmentStatus.LOADED,
            driver_id=driver_b.pk,
        )
        booking.shipments = MagicMock()
        booking.shipments.all.return_value = [outbound, backload]

        ctx = JobDetailContext(
            driver=driver_b,
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(backload.pk),
            shipment=backload,
            booking=booking,
        )
        section = build_round_trip_section(ctx)

        self.assertEqual(section['progression_mode'], 'split_driver')
        self.assertTrue(section['backload_progression']['driver_owns_any_leg'])
        self.assertFalse(section['outbound_progression']['driver_owns_any_leg'])
        self.assertTrue(section['current_leg']['driver_owns_leg'])

    def test_movement_job_omits_round_trip(self):
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='movement',
            job_id='m1',
            movement=MagicMock(),
        )
        self.assertEqual(build_round_trip_section(ctx), {})
