"""
API integration tests for POST POD capture (mocked orchestrator / auth).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from mobile_api.authentication import MobileUser
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.views.pod_capture_view import PodCaptureAPIView
from mobile_api.rbac import request_has_capability


def _jwt_payload(*, schema='tenant_test', user_id=None, driver_id=None, role_name='Driver'):
    return {
        'user_id': str(user_id or uuid4()),
        'tenant_schema': schema,
        'driver_id': str(driver_id or uuid4()),
        'role_name': role_name,
        'email': 'driver@test.com',
        'jti': str(uuid4()),
    }


def _driver(pk=None):
    d = MagicMock()
    d.pk = pk or uuid4()
    d.driver_id = d.pk
    d.driver_name = 'Test Driver'
    return d


def _capture_payload(**overrides):
    base = {
        'client_capture_id': str(uuid4()),
        'workflow_version': 'wf-pre',
        'content_hash': 'hash-pre',
        'pod_type': 'digital',
        'notes': 'POD staged',
        'latitude': 25.0,
        'longitude': 55.0,
        'media': [
            {
                'media_type': 'photo',
                'file_ref': (
                    'mobile_driver_uploads/tenant_test/'
                    f'{uuid4()}/ship-1/pod_capture/photo.jpg'
                ),
            },
        ],
    }
    base.update(overrides)
    return base


def _success_capture_data(*, replayed=False, bundle_id=None):
    bundle_id = bundle_id or str(uuid4())
    return {
        'capture_bundle': {
            'capture_bundle_id': bundle_id,
            'bundle_id': bundle_id,
            'client_capture_id': 'cap-1',
            'shipment_id': 'ship-1',
            'status': 'ready',
            'media_count': 1,
            'replayed': replayed,
            'execute_ready': True,
            'staged_media': [
                {
                    'media_id': str(uuid4()),
                    'media_type': 'photo',
                    'file_ref': 'mobile_driver_uploads/tenant_test/d1/ship-1/pod_capture/p.jpg',
                },
            ],
            'promotion': {'ready_for_execute': True, 'promoted': False},
        },
        'compliance': {
            'validated': True,
            'pod_type': 'digital',
            'target_action_code': 'POD_CAP',
            'requirements': {'gps': True, 'photo': True, 'photo_min_count': 1},
            'summary': {
                'gps_satisfied': True,
                'media_count': 1,
                'photo_count': 1,
            },
        },
        'sync_metadata': {
            'content_hash': 'hash-post',
            'workflow_version': 'wf-post',
        },
        'next_step': {
            'requires_execute_action': True,
            'bundle_id': bundle_id,
            'capture_bundle_id': bundle_id,
            'target_action_code': 'POD_CAP',
            'execute_ready': True,
        },
    }


class PodCaptureAPITests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = APIRequestFactory()
        self.view = PodCaptureAPIView.as_view()

    def _request(self, shipment_id=None, *, data=None, jwt_payload=None):
        shipment_id = shipment_id or str(uuid4())
        driver = _driver()
        payload = jwt_payload or _jwt_payload(driver_id=driver.pk)
        url = reverse(
            'mobile_api:driver_pod_capture',
            kwargs={'shipment_id': shipment_id},
        )
        request = self.factory.post(
            url,
            data=data or _capture_payload(),
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token',
            HTTP_X_TENANT_ID=payload.get('tenant_schema', 'tenant_test'),
        )
        force_authenticate(request, user=MobileUser(payload), token=payload)
        return request, shipment_id, driver, payload

    @patch('mobile_api.pod_capture.views.pod_capture_view.resolve_mobile_driver_session')
    @patch('mobile_api.pod_capture.views.pod_capture_view.tenant_schema_for_request')
    @patch('mobile_api.pod_capture.views.pod_capture_view.PodCaptureOrchestrator')
    def test_capture_success_contract(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ) -> None:
        request, shipment_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        mock_orch_cls.return_value.capture_pod_evidence.return_value = _success_capture_data()

        response = self.view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 1)
        data = response.data['data']
        self.assertEqual(
            set(data.keys()),
            {'capture_bundle', 'compliance', 'sync_metadata', 'next_step'},
        )
        self.assertEqual(data['capture_bundle']['capture_bundle_id'], data['capture_bundle']['bundle_id'])
        self.assertTrue(data['next_step']['requires_execute_action'])
        self.assertTrue(data['compliance']['validated'])
        self.assertEqual(len(data['capture_bundle']['staged_media']), 1)

    @patch('mobile_api.pod_capture.views.pod_capture_view.resolve_mobile_driver_session')
    @patch('mobile_api.pod_capture.views.pod_capture_view.tenant_schema_for_request')
    @patch('mobile_api.pod_capture.views.pod_capture_view.PodCaptureOrchestrator')
    def test_idempotent_replay_returns_200(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ) -> None:
        request, shipment_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        mock_orch_cls.return_value.capture_pod_evidence.return_value = _success_capture_data(
            replayed=True,
        )

        response = self.view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['data']['capture_bundle']['replayed'])

    @patch('mobile_api.pod_capture.views.pod_capture_view.resolve_mobile_driver_session')
    @patch('mobile_api.pod_capture.views.pod_capture_view.tenant_schema_for_request')
    def test_tenant_required(self, mock_tenant_schema, mock_resolve_session) -> None:
        request, shipment_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = ''
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)

        response = self.view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['data']['error_code'], 'tenant_required')

    @patch('mobile_api.pod_capture.views.pod_capture_view.resolve_mobile_driver_session')
    @patch('mobile_api.pod_capture.views.pod_capture_view.tenant_schema_for_request')
    def test_driver_session_required(self, mock_tenant_schema, mock_resolve_session) -> None:
        request, shipment_id, _driver, _payload = self._request()
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (None, None, 'Unauthorized', 'unauthorized')

        response = self.view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 401)

    @patch('mobile_api.pod_capture.views.pod_capture_view.resolve_mobile_driver_session')
    @patch('mobile_api.pod_capture.views.pod_capture_view.tenant_schema_for_request')
    @patch('mobile_api.pod_capture.views.pod_capture_view.PodCaptureOrchestrator')
    def test_ownership_forbidden(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ) -> None:
        request, shipment_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        mock_orch_cls.return_value.capture_pod_evidence.side_effect = PodCaptureError(
            'forbidden',
            code='forbidden',
            http_status=403,
            message_key='mobile.auth.forbidden',
        )

        response = self.view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 403)

    @patch('mobile_api.pod_capture.views.pod_capture_view.resolve_mobile_driver_session')
    @patch('mobile_api.pod_capture.views.pod_capture_view.tenant_schema_for_request')
    @patch('mobile_api.pod_capture.views.pod_capture_view.PodCaptureOrchestrator')
    def test_validation_error_from_orchestrator(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ) -> None:
        request, shipment_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        mock_orch_cls.return_value.capture_pod_evidence.side_effect = PodCaptureError(
            'signature required',
            code='signature_required',
            http_status=400,
            message_key='mobile.pod_capture.signature_required',
        )

        response = self.view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['data']['error_code'], 'signature_required')

    @patch('mobile_api.pod_capture.views.pod_capture_view.resolve_mobile_driver_session')
    @patch('mobile_api.pod_capture.views.pod_capture_view.tenant_schema_for_request')
    @patch('mobile_api.pod_capture.views.pod_capture_view.PodCaptureOrchestrator')
    def test_orphan_upload_security_error(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ) -> None:
        request, shipment_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        mock_orch_cls.return_value.capture_pod_evidence.side_effect = PodCaptureError(
            'orphan upload',
            code='orphan_upload',
            http_status=403,
            message_key='mobile.pod_capture.orphan_upload',
        )

        response = self.view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['data']['error_code'], 'orphan_upload')

    def test_missing_client_capture_id_400(self) -> None:
        request, shipment_id, _driver, _payload = self._request(
            data={
                'workflow_version': 'wf',
                'content_hash': 'h',
                'latitude': 1.0,
                'longitude': 2.0,
                'notes': '',
                'media': [{'media_type': 'photo', 'file_ref': 'x.jpg'}],
            },
        )

        response = self.view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 400)

    @patch('mobile_api.pod_capture.views.pod_capture_view.resolve_mobile_driver_session')
    @patch('mobile_api.pod_capture.views.pod_capture_view.tenant_schema_for_request')
    @patch('mobile_api.pod_capture.views.pod_capture_view.PodCaptureOrchestrator')
    def test_payload_passed_to_orchestrator(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ) -> None:
        request, shipment_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        mock_orch_cls.return_value.capture_pod_evidence.return_value = _success_capture_data()

        self.view(request, shipment_id=shipment_id)

        call_kwargs = mock_orch_cls.return_value.capture_pod_evidence.call_args.kwargs
        self.assertEqual(call_kwargs['shipment_id'], shipment_id)
        self.assertEqual(call_kwargs['tenant_schema'], 'tenant_test')
        self.assertEqual(call_kwargs['job_type'], 'shipment')
        self.assertEqual(call_kwargs['payload']['pod_type'], 'digital')


class PodCaptureRBACTests(SimpleTestCase):
    def test_driver_has_pod_capture_capability(self) -> None:
        request = MagicMock()
        request.auth = _jwt_payload()
        self.assertTrue(
            request_has_capability(request, 'mobile.driver.pod_capture'),
        )

    def test_dispatcher_lacks_pod_capture_capability(self) -> None:
        request = MagicMock()
        request.auth = {
            **_jwt_payload(),
            'driver_id': '',
            'role_name': 'Dispatcher',
        }
        self.assertFalse(
            request_has_capability(request, 'mobile.driver.pod_capture'),
        )

    def test_execute_capability_distinct_from_pod_capture(self) -> None:
        request = MagicMock()
        request.auth = _jwt_payload()
        self.assertTrue(request_has_capability(request, 'mobile.driver.pod_capture'))
        self.assertTrue(request_has_capability(request, 'mobile.driver.execute'))


class PodCaptureResponseBuilderTests(SimpleTestCase):
    def test_response_builder_contract(self) -> None:
        from datetime import timedelta

        from django.utils import timezone

        from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
        from mobile_api.pod_capture.dto.pod_capture_response_builder import (
            PodCaptureResponseBuilder,
        )
        from mobile_api.pod_capture.dto.staging_models import (
            PODCaptureBundle,
            PODCaptureBundleStatus,
            PODCaptureMedia,
        )

        now = timezone.now()
        bundle = PODCaptureBundle(
            bundle_id='bundle-abc',
            client_capture_id='cap-1',
            shipment_id='ship-1',
            driver_id='drv-1',
            tenant_schema='tenant_a',
            status=PODCaptureBundleStatus.READY,
            content_hash='h1',
            media_count=1,
            expires_at=now + timedelta(hours=24),
            created_at=now,
            updated_at=now,
        )
        media = PODCaptureMedia(
            media_id='m1',
            bundle_id='bundle-abc',
            shipment_id='ship-1',
            driver_id='drv-1',
            tenant_schema='tenant_a',
            client_capture_id='cap-1',
            media_type='photo',
            file_ref='mobile_driver_uploads/tenant_a/drv-1/ship-1/pod_capture/p.jpg',
        )
        ctx = PodCaptureContext(
            driver=MagicMock(pk='drv-1'),
            tenant_schema='tenant_a',
            shipment_id='ship-1',
            payload={},
        )
        ctx.bundle = bundle
        ctx.staged_media = [media]
        ctx.pod_capture_type = 'digital'
        ctx.target_action_code = 'POD_CAP'
        ctx.compliance_requirements = {'gps': True, 'photo': True, 'photo_min_count': 1}
        ctx.latitude = '25.0'
        ctx.longitude = '55.0'

        data = PodCaptureResponseBuilder().build(ctx)

        self.assertEqual(data['capture_bundle']['capture_bundle_id'], 'bundle-abc')
        self.assertTrue(data['next_step']['requires_execute_action'])
        self.assertTrue(data['compliance']['summary']['gps_satisfied'])
