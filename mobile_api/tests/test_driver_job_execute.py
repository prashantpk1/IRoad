"""
Execute-action API tests — validation, idempotency contract, view wiring.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from mobile_api.helpers.action_execution_validation import (
    validate_mobile_execution_payload,
)
from mobile_api.serializers.driver_job_execute import (
    ExecuteActionResponseDataSerializer,
    ExecuteDriverActionSerializer,
)


class ExecuteActionSerializerTests(SimpleTestCase):
    def test_request_requires_action_id(self):
        ser = ExecuteDriverActionSerializer(data={})
        self.assertFalse(ser.is_valid())
        self.assertIn('action_id', ser.errors)

    def test_response_schema_accepts_workflow_refresh(self):
        action_id = uuid4()
        log_id = uuid4()
        job_id = uuid4()
        data = {
            'execution': {
                'log_id': str(log_id),
                'log_no': 'OAL-0001',
                'log_date': '2026-05-21T10:00:00+00:00',
                'action_code': 'A5',
                'action_label': 'Depart',
                'reused_existing': False,
                'source_channel': 'mobile_driver',
                'media_saved_count': 0,
            },
            'workflow': {
                'allowed_actions': {
                    'job_type': 'shipment',
                    'job_id': str(job_id),
                    'job_no': 'SH-1',
                    'current_stage': 'In Transit',
                    'context_label': 'ctx',
                    'count': 0,
                    'workflow_source': 'operation_execution.get_allowed_actions',
                    'actions': [],
                    'primary_action': None,
                },
                'execution_state': {
                    'shipment_status': 'In Transit',
                    'derived_status': 'In Transit',
                    'operational_stage': 'In Transit',
                    'in_sync': True,
                },
                'latest_action': None,
                'shipment_status': 'In Transit',
                'movement_status': None,
                'operational_stage': 'In Transit',
            },
        }
        ser = ExecuteActionResponseDataSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)


class ExecutionValidationTests(SimpleTestCase):
    def test_gps_required_when_metadata_says_so(self):
        action = MagicMock()
        action.action_code = 'A5'
        request = MagicMock()
        request.data = {'notes': 'ok'}

        with patch(
            'mobile_api.helpers.action_execution_validation.build_execution_requirements',
            return_value={'gps': True, 'photo': False, 'photo_min_count': 0},
        ):
            with self.assertRaises(ValidationError):
                validate_mobile_execution_payload(
                    operation_action=action,
                    request=request,
                )

    def test_cod_parsed_for_a9(self):
        action = MagicMock()
        action.action_code = 'A9'
        shipment = MagicMock()
        shipment.cod_amount = None
        request = MagicMock()
        request.data = {
            'latitude': '24.5',
            'longitude': '46.7',
            'cod_amount': '150.00',
        }

        with patch(
            'mobile_api.helpers.action_execution_validation.build_execution_requirements',
            return_value={'gps': False, 'photo': False, 'photo_min_count': 0},
        ):
            with patch(
                'mobile_api.helpers.action_execution_validation.action_matches',
                return_value=True,
            ):
                payload = validate_mobile_execution_payload(
                    operation_action=action,
                    request=request,
                    shipment=shipment,
                )
        self.assertEqual(payload['cod_amount'], Decimal('150.00'))


class ExecuteActionViewTests(SimpleTestCase):
    def test_shipment_execute_success(self):
        from rest_framework.test import APIRequestFactory
        from mobile_api.views.driver_job_execute import DriverShipmentExecuteActionView

        action_id = uuid4()
        shipment_id = uuid4()
        log_id = uuid4()
        factory = APIRequestFactory()
        request = factory.post(
            '/api/v1/mobile/driver/jobs/shipments/%s/actions/execute/' % shipment_id,
            {
                'action_id': str(action_id),
                'idempotency_key': 'idem-1',
                'latitude': '24.5',
                'longitude': '46.7',
            },
            format='json',
        )
        request.auth = {
            'tenant_schema': 'tenant_a',
            'driver_id': str(uuid4()),
            'sub': str(uuid4()),
        }

        engine_payload = {
            'job_type': 'shipment',
            'job_id': str(shipment_id),
            'job_no': 'SH-1',
            'current_stage': 'In Transit',
            'context_label': 'ctx',
            'count': 0,
            'workflow_source': 'operation_execution.get_allowed_actions',
            'actions': [],
            'primary_action': None,
        }

        exec_result = {
            'success': True,
            'execution': {
                'log_id': str(log_id),
                'log_no': 'OAL-1',
                'log_date': '2026-05-21T10:00:00+00:00',
                'action_code': 'A5',
                'action_label': 'Depart',
                'reused_existing': False,
                'source_channel': 'mobile_driver',
                'media_saved_count': 0,
            },
            'workflow': {
                'allowed_actions': engine_payload,
                'execution_state': {
                    'shipment_status': 'In Transit',
                    'derived_status': 'In Transit',
                    'operational_stage': 'In Transit',
                    'in_sync': True,
                },
                'latest_action': None,
                'shipment_status': 'In Transit',
                'movement_status': None,
                'operational_stage': 'In Transit',
            },
        }

        view = DriverShipmentExecuteActionView.as_view()

        with patch(
            'mobile_api.permissions.HasDriverJobsExecuteAccess.has_permission',
            return_value=True,
        ):
            with patch(
                'mobile_api.permissions.IsMobileAuthenticated.has_permission',
                return_value=True,
            ):
                with patch(
                    'mobile_api.views.driver_job_execution_base.resolve_secure_job_execution_context',
                    return_value={
                        'success': True,
                        'ctx': MagicMock(
                            driver=MagicMock(pk=uuid4()),
                            tenant_user=MagicMock(user_id=uuid4()),
                        ),
                    },
                ):
                    with patch(
                        'mobile_api.views.driver_job_execute.DriverJobExecuteService.execute_shipment_action',
                        return_value=exec_result,
                    ):
                        response = view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['execution']['log_no'], 'OAL-1')
        self.assertFalse(response.data['data']['execution']['reused_existing'])

    def test_execute_returns_403_when_action_not_allowed(self):
        from rest_framework.test import APIRequestFactory
        from mobile_api.views.driver_job_execute import DriverShipmentExecuteActionView

        shipment_id = uuid4()
        factory = APIRequestFactory()
        request = factory.post(
            '/api/v1/mobile/driver/jobs/shipments/%s/actions/execute/' % shipment_id,
            {'action_id': str(uuid4())},
            format='json',
        )
        request.auth = {
            'tenant_schema': 'tenant_a',
            'driver_id': str(uuid4()),
            'sub': str(uuid4()),
        }

        view = DriverShipmentExecuteActionView.as_view()

        with patch(
            'mobile_api.permissions.HasDriverJobsExecuteAccess.has_permission',
            return_value=True,
        ):
            with patch(
                'mobile_api.permissions.IsMobileAuthenticated.has_permission',
                return_value=True,
            ):
                with patch(
                    'mobile_api.views.driver_job_execution_base.resolve_secure_job_execution_context',
                    return_value={
                        'success': True,
                        'ctx': MagicMock(
                            driver=MagicMock(pk=uuid4()),
                            tenant_user=MagicMock(user_id=uuid4()),
                        ),
                    },
                ):
                    with patch(
                        'mobile_api.views.driver_job_execute.DriverJobExecuteService.execute_shipment_action',
                        return_value={
                            'success': False,
                            'code': 'action_not_allowed',
                            'error': 'Action not allowed',
                        },
                    ):
                        response = view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 403)
