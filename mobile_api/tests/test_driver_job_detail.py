"""
Job Detail snapshot API tests (mocked ORM, no DB required).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from mobile_api.helpers.job_detail_projections import build_job_detail_dto
from mobile_api.serializers.driver_job_detail import JobDetailSnapshotSerializer
from mobile_api.views.driver_job_detail import DriverShipmentJobDetailView


class JobDetailProjectionTests(SimpleTestCase):
    def test_build_job_detail_dto_shipment_shape(self):
        shipment_id = str(uuid4())
        driver = MagicMock()
        driver.driver_id = uuid4()
        driver.driver_code = 'DRV-1'
        driver.english_name = 'Test Driver'
        driver.arabic_name = ''

        shipment_row = MagicMock()
        shipment_row.shipment_id = shipment_id
        shipment_row.shipment_no = 'SH-001'
        shipment_row.shipment_status = 'In Transit'
        shipment_row.pod_status = 'Pending'
        shipment_row.order_type = 'COD'
        shipment_row.collection_status = 'Pending'
        shipment_row.updated_at = None
        shipment_row.truck = None

        raw = {
            'job_type': 'shipment',
            'job_id': shipment_id,
            'job_no': 'SH-001',
            'shipment': {
                'shipment_id': shipment_id,
                'shipment_no': 'SH-001',
                'shipment_status': 'In Transit',
                'booking_no': 'BK-1',
                'order_type': 'COD',
                'sourcing_mode': 'In-Source',
                'shipment_date': '2026-05-21',
            },
            'movement': None,
            'status': {
                'shipment_status': 'In Transit',
                'movement_status': None,
                'operational_stage': 'In Transit',
                'has_active_movement': False,
            },
            'execution_state': {
                'shipment_status': 'In Transit',
                'derived_status': 'In Transit',
                'operational_stage': 'In Transit',
                'in_sync': True,
            },
            'route': {'summary': 'A → B', 'from_label': 'A', 'to_label': 'B'},
            'latest_action': None,
            'pod': {'status': 'Pending', 'is_pending': True, 'needs_attention': True},
            'cod': {
                'order_type': 'COD',
                'cod_amount': '100',
                'collection_status': 'Pending',
                'is_cod_order': True,
                'is_collection_pending': True,
            },
            'allowed_actions': {
                'job_type': 'shipment',
                'job_id': shipment_id,
                'job_no': 'SH-001',
                'current_stage': 'In Transit',
                'context_label': 'Allowed actions for shipment status: In Transit',
                'count': 1,
                'workflow_source': 'operation_execution.get_allowed_actions',
                'actions': [
                    {
                        'action_id': str(uuid4()),
                        'action_code': 'A5',
                        'action_name': 'Depart',
                        'execution_label': 'Depart',
                        'requires_gps': True,
                        'requires_photo': False,
                        'requires_video': False,
                        'requires_note': False,
                        'action_category': 'Job',
                        'execution_order': 5,
                        'sort_index': 0,
                        'current_stage': 'In Transit',
                        'execution_requirements': {
                            'gps': True,
                            'photo': False,
                            'photo_min_count': 0,
                            'video': False,
                            'video_min_count': 0,
                            'note': False,
                            'note_required': False,
                            'signature': False,
                            'auto_movement_post': False,
                            'auto_pod_post': False,
                            'auto_shipment_post': False,
                            'hard_copy_collection': False,
                            'shipment_status_impact': 'In Transit',
                            'movement_status_impact': '',
                        },
                    }
                ],
                'primary_action': None,
            },
            'timeline_preview': [],
        }

        raw['allowed_actions']['primary_action'] = raw['allowed_actions']['actions'][0]

        dto = build_job_detail_dto(
            raw_snapshot=raw,
            driver=driver,
            shipment_row=shipment_row,
            movement_row=None,
        )
        ser = JobDetailSnapshotSerializer(data=dto)
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data['job_type'], 'shipment')
        self.assertEqual(ser.validated_data['allowed_actions_summary']['count'], 1)
        self.assertTrue(ser.validated_data['operational_indicators']['needs_pod'])


class DriverShipmentJobDetailViewTests(SimpleTestCase):
    def test_get_returns_404_when_not_found(self):
        factory = APIRequestFactory()
        request = factory.get('/api/v1/mobile/driver/jobs/shipments/%s/' % uuid4())
        request.user = MagicMock()
        request.auth = {
            'tenant_schema': 'tenant_a',
            'driver_id': str(uuid4()),
            'sub': str(uuid4()),
        }

        view = DriverShipmentJobDetailView.as_view()

        with patch(
            'mobile_api.permissions.HasDriverJobsAccess.has_permission',
            return_value=True,
        ):
            with patch(
                'mobile_api.permissions.IsMobileAuthenticated.has_permission',
                return_value=True,
            ):
                with patch(
                    'mobile_api.views.driver_job_detail.resolve_secure_job_list_context',
                    return_value={
                        'success': True,
                        'ctx': MagicMock(
                            driver=MagicMock(pk=uuid4()),
                            tenant_user=MagicMock(user_id=uuid4()),
                            tenant_schema='tenant_a',
                        ),
                    },
                ):
                    with patch(
                        'mobile_api.views.driver_job_detail.DriverJobDetailService.get_shipment_job_detail',
                        return_value={
                            'success': False,
                            'code': 'job_not_found',
                            'error': 'not found',
                        },
                    ):
                        response = view(
                            request,
                            shipment_id=uuid4(),
                        )

        self.assertEqual(response.status_code, 404)
