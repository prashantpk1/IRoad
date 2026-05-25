"""
POD / COD mobile API tests.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from mobile_api.helpers.pod_cod_validation import validate_cod_collection_compliance
from mobile_api.serializers.driver_job_pod_cod import (
    CodCollectionResponseDataSerializer,
    PodUploadResponseDataSerializer,
)


class CodValidationTests(SimpleTestCase):
    def test_rejects_non_cod_shipment(self):
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.order_type = 'Standard'
        shipment.collection_status = ''
        shipment.shipment_status = 'In Transit'
        action = MagicMock()

        with patch(
            'mobile_api.helpers.pod_cod_validation.validate_shipment_compliance_context',
        ):
            with self.assertRaises(ValidationError):
                validate_cod_collection_compliance(
                    shipment=shipment,
                    driver=MagicMock(),
                    operation_action=action,
                    cod_amount_raw='100',
                )


class PodCodSerializerTests(SimpleTestCase):
    def test_pod_response_schema(self):
        job_id = uuid4()
        log_id = uuid4()
        data = {
            'operation': 'upload_pod',
            'execution': {
                'log_id': str(log_id),
                'log_no': 'OAL-1',
                'log_date': '2026-05-21T10:00:00+00:00',
                'action_code': 'A7',
                'action_label': 'Upload POD',
                'reused_existing': False,
                'source_channel': 'mobile_driver',
                'media_saved_count': 1,
            },
            'workflow': {
                'allowed_actions': {
                    'job_type': 'shipment',
                    'job_id': str(job_id),
                    'job_no': 'SH-1',
                    'current_stage': 'At Delivery',
                    'context_label': 'ctx',
                    'count': 0,
                    'actions': [],
                    'primary_action': None,
                    'workflow_source': 'operation_execution.get_allowed_actions',
                },
                'execution_state': {
                    'shipment_status': 'At Delivery',
                    'derived_status': 'At Delivery',
                    'operational_stage': 'Delivery',
                    'in_sync': True,
                },
                'latest_action': None,
                'shipment_status': 'At Delivery',
                'movement_status': None,
                'operational_stage': 'Delivery',
            },
            'compliance': {
                'pod': {
                    'pod_status': 'Pending',
                    'pod_type': 'Digital',
                    'needs_attention': True,
                    'is_pending': True,
                    'shipment_status': 'At Delivery',
                    'document': None,
                },
            },
        }
        ser = PodUploadResponseDataSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)


class PodCodViewTests(SimpleTestCase):
    def test_upload_pod_view_success(self):
        from rest_framework.test import APIRequestFactory
        from mobile_api.views.driver_job_pod_cod import DriverShipmentUploadPodView

        shipment_id = uuid4()
        factory = APIRequestFactory()
        request = factory.post(
            '/api/v1/mobile/driver/jobs/shipments/%s/upload-pod/' % shipment_id,
            {
                'notes': 'POD at gate',
                'latitude': '24.5',
                'longitude': '46.6',
            },
        )
        request.auth = {'tenant_schema': 't', 'driver_id': str(uuid4()), 'sub': str(uuid4())}

        result = {
            'success': True,
            'operation': 'upload_pod',
            'execution': {
                'log_id': str(uuid4()),
                'log_no': 'OAL-9',
                'log_date': '2026-05-21T10:00:00+00:00',
                'action_code': 'A7',
                'action_label': 'Upload POD',
                'reused_existing': False,
                'source_channel': 'mobile_driver',
                'media_saved_count': 1,
            },
            'workflow': {
                'allowed_actions': {
                    'job_type': 'shipment',
                    'job_id': str(shipment_id),
                    'job_no': 'SH-1',
                    'current_stage': 'At Delivery',
                    'context_label': 'c',
                    'count': 0,
                    'actions': [],
                    'primary_action': None,
                    'workflow_source': 'operation_execution.get_allowed_actions',
                },
                'execution_state': {
                    'shipment_status': 'At Delivery',
                    'derived_status': 'At Delivery',
                    'operational_stage': 'At Delivery',
                    'in_sync': True,
                },
                'latest_action': None,
                'shipment_status': 'At Delivery',
                'movement_status': None,
                'operational_stage': 'At Delivery',
            },
            'compliance': {
                'pod': {
                    'pod_status': 'Pending',
                    'pod_type': 'Digital',
                    'needs_attention': True,
                    'is_pending': True,
                    'shipment_status': 'At Delivery',
                    'document': None,
                },
            },
        }

        view = DriverShipmentUploadPodView.as_view()
        with patch('mobile_api.permissions.HasDriverJobsExecuteAccess.has_permission', return_value=True):
            with patch('mobile_api.permissions.IsMobileAuthenticated.has_permission', return_value=True):
                with patch(
                    'mobile_api.views.driver_job_pod_cod.request_may_upload_pod',
                    return_value=True,
                ):
                    with patch(
                        'mobile_api.views.driver_job_execution_base.resolve_secure_job_execution_context',
                        return_value={'success': True, 'ctx': MagicMock(driver=MagicMock(), tenant_user=MagicMock())},
                    ):
                        with patch(
                            'mobile_api.views.driver_job_pod_cod.DriverJobPodCodService.upload_pod',
                            return_value=result,
                        ):
                            response = view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['operation'], 'upload_pod')
