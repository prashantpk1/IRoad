"""
Integration-style tests for GET /api/v1/mobile/driver/jobs/<job_type>/<job_id>/.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from mobile_api.authentication import MobileUser
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.exceptions import JobDetailError
from mobile_api.job_detail.services.job_detail_context_service import (
    JobDetailContextService,
    JobDetailResolveResult,
)
from mobile_api.job_detail.views.job_detail_view import JobDetailAPIView
from mobile_api.rbac import request_has_capability
from tenant_workspace.models import TenantShipment, TenantTruckMovementLog


def _jwt_payload(*, schema='tenant_test', user_id=None, driver_id=None):
    return {
        'user_id': str(user_id or uuid4()),
        'tenant_schema': schema,
        'driver_id': str(driver_id or uuid4()),
        'role_name': 'Driver',
        'email': 'driver@test.com',
        'jti': str(uuid4()),
    }


def _driver(pk=None):
    d = MagicMock()
    d.pk = pk or uuid4()
    d.driver_id = d.pk
    return d


def _shipment_context(driver) -> JobDetailContext:
    shipment = MagicMock()
    shipment.pk = uuid4()
    shipment.shipment_id = shipment.pk
    shipment.shipment_no = 'SH-900'
    shipment.driver_id = driver.pk
    booking = MagicMock()
    booking.pk = uuid4()
    booking.booking_no = 'BK-100'
    return JobDetailContext(
        driver=driver,
        tenant_schema='tenant_test',
        user_id=str(uuid4()),
        job_type='shipment',
        job_id=str(shipment.pk),
        shipment=shipment,
        booking=booking,
        job_header={
            'job_type': 'shipment',
            'job_id': str(shipment.pk),
            'job_no': 'SH-900',
            'entity_type': 'shipment',
        },
        workflow={
            'current_stage': 'In Transit',
            'next_action': {'action_code': 'A5'},
            'primary_action': {'action_code': 'A5'},
            'allowed_actions': [{'action_code': 'A5'}],
            'workflow_source': 'operation_execution.get_allowed_actions',
        },
        timeline={
            'scope': 'shipment',
            'timeline_preview': [{'event_id': 'e1'}],
            'timeline_cursor': '',
            'has_more': False,
        },
        pod_cod={
            'pod_pending': True,
            'pod_compliant': False,
            'hard_pod_pending': False,
            'cod_pending': False,
            'cod_collected': False,
            'treasury_pending': False,
            'delivery_blocked': False,
        },
        round_trip={
            'booking_execution_stage': 'PARTIAL',
            'progression_mode': 'same_driver',
        },
        alerts={},
        sync_metadata={
            'content_hash': 'abc' * 21 + 'a',
            'entity_versions': {'shipment': 'v1', 'action_log': ''},
            'workflow_version': 'wf1',
            'generated_at': '2026-05-26T00:00:00+00:00',
        },
        content_hash='abc' * 21 + 'a',
        job_etag='"etag-value"',
    )


def _movement_context(driver) -> JobDetailContext:
    movement = MagicMock()
    movement.pk = uuid4()
    movement.movement_id = movement.pk
    movement.movement_no = 'EM-50'
    movement.driver_id = driver.pk
    return JobDetailContext(
        driver=driver,
        tenant_schema='tenant_test',
        user_id=str(uuid4()),
        job_type='movement',
        job_id=str(movement.pk),
        movement=movement,
        job_header={
            'job_type': 'movement',
            'job_id': str(movement.pk),
            'job_no': 'EM-50',
            'entity_type': 'movement',
        },
        workflow={
            'current_stage': 'Scheduled',
            'allowed_actions': [],
            'workflow_source': 'operation_execution.get_allowed_actions',
        },
        timeline={'scope': 'movement', 'timeline_preview': [], 'has_more': False},
        sync_metadata={
            'content_hash': 'movhash',
            'entity_versions': {'movement': 'mv1'},
            'workflow_version': 'wfm',
            'generated_at': '2026-05-26T00:00:00+00:00',
        },
        content_hash='movhash',
    )


class JobDetailAPIIntegrationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.shipment_url = reverse(
            'mobile_api:driver_job_detail',
            kwargs={'job_type': 'shipment', 'job_id': str(uuid4())},
        )
        self.movement_url = reverse(
            'mobile_api:driver_job_detail',
            kwargs={'job_type': 'movement', 'job_id': str(uuid4())},
        )

    @patch('mobile_api.job_detail.views.job_detail_view.JobDetailContextService')
    @patch('mobile_api.job_detail.views.job_detail_view.resolve_job_detail_driver')
    def test_get_shipment_job_detail_success(self, mock_resolve, mock_svc_cls):
        driver = _driver()
        mock_resolve.return_value = (driver, None, None)
        context = _shipment_context(driver)

        mock_svc = mock_svc_cls.return_value
        mock_svc.resolve_job_detail.return_value = JobDetailResolveResult(
            context=context,
            etag=context.job_etag,
            not_modified=False,
        )
        mock_svc.build_api_payload.return_value = {
            'job': context.job_header,
            'workflow': context.workflow,
            'timeline': context.timeline,
            'pod_cod': context.pod_cod,
            'round_trip': context.round_trip,
            'alerts': context.alerts,
            'sync_metadata': context.sync_metadata,
        }

        request = self.factory.get(self.shipment_url)
        payload = _jwt_payload(driver_id=driver.driver_id)
        force_authenticate(request, user=MobileUser(payload), token=payload)
        response = JobDetailAPIView.as_view()(
            request,
            job_type='shipment',
            job_id=str(context.job_id),
        )

        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['job']['job_no'], 'SH-900')
        self.assertEqual(data['workflow']['current_stage'], 'In Transit')
        self.assertTrue(data['pod_cod']['pod_pending'])
        self.assertEqual(data['round_trip']['progression_mode'], 'same_driver')
        self.assertTrue(data['sync_metadata']['content_hash'])
        self.assertIn('ETag', response)

    @patch('mobile_api.job_detail.views.job_detail_view.JobDetailContextService')
    @patch('mobile_api.job_detail.views.job_detail_view.resolve_job_detail_driver')
    def test_get_movement_job_detail_omits_pod_round_trip(
        self, mock_resolve, mock_svc_cls
    ):
        driver = _driver()
        mock_resolve.return_value = (driver, None, None)
        context = _movement_context(driver)

        mock_svc = mock_svc_cls.return_value
        mock_svc.resolve_job_detail.return_value = JobDetailResolveResult(
            context=context,
            not_modified=False,
        )
        mock_svc.build_api_payload.return_value = {
            'job': context.job_header,
            'workflow': context.workflow,
            'timeline': context.timeline,
            'pod_cod': {},
            'round_trip': {},
            'alerts': {},
            'sync_metadata': context.sync_metadata,
        }

        request = self.factory.get(self.movement_url)
        force_authenticate(
            request,
            user=MobileUser(_jwt_payload(driver_id=driver.driver_id)),
            token=_jwt_payload(driver_id=driver.driver_id),
        )
        response = JobDetailAPIView.as_view()(
            request,
            job_type='movement',
            job_id=str(context.job_id),
        )

        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertEqual(data['job']['job_no'], 'EM-50')
        self.assertEqual(data['pod_cod'], {})
        self.assertEqual(data['round_trip'], {})

    @patch('mobile_api.job_detail.views.job_detail_view.resolve_job_detail_driver')
    def test_get_job_detail_auth_failure(self, mock_resolve):
        mock_resolve.return_value = (None, 'Unauthorized', 'unauthorized')
        request = self.factory.get(self.shipment_url)
        force_authenticate(
            request,
            user=MobileUser(_jwt_payload()),
            token=_jwt_payload(),
        )
        response = JobDetailAPIView.as_view()(
            request,
            job_type='shipment',
            job_id='x',
        )
        self.assertEqual(response.status_code, 401)

    @patch('mobile_api.job_detail.views.job_detail_view.JobDetailContextService')
    @patch('mobile_api.job_detail.views.job_detail_view.resolve_job_detail_driver')
    def test_get_job_detail_not_found(self, mock_resolve, mock_svc_cls):
        driver = _driver()
        mock_resolve.return_value = (driver, None, None)
        mock_svc_cls.return_value.resolve_job_detail.side_effect = JobDetailError(
            'Not found',
            code='job_not_found',
            http_status=404,
            message_key='mobile.jobs.not_found',
        )

        request = self.factory.get(self.shipment_url)
        force_authenticate(
            request,
            user=MobileUser(_jwt_payload(driver_id=driver.driver_id)),
            token=_jwt_payload(driver_id=driver.driver_id),
        )
        response = JobDetailAPIView.as_view()(
            request,
            job_type='shipment',
            job_id='missing',
        )
        self.assertEqual(response.status_code, 404)

    @patch('mobile_api.job_detail.views.job_detail_view.JobDetailContextService')
    @patch('mobile_api.job_detail.views.job_detail_view.resolve_job_detail_driver')
    def test_get_job_detail_forbidden(self, mock_resolve, mock_svc_cls):
        driver = _driver()
        mock_resolve.return_value = (driver, None, None)
        mock_svc_cls.return_value.resolve_job_detail.side_effect = JobDetailError(
            'Forbidden',
            code='forbidden',
            http_status=403,
            message_key='mobile.auth.forbidden',
        )

        request = self.factory.get(self.shipment_url)
        force_authenticate(
            request,
            user=MobileUser(_jwt_payload(driver_id=driver.driver_id)),
            token=_jwt_payload(driver_id=driver.driver_id),
        )
        response = JobDetailAPIView.as_view()(
            request,
            job_type='shipment',
            job_id='other',
        )
        self.assertEqual(response.status_code, 403)

    @patch('mobile_api.job_detail.views.job_detail_view.JobDetailContextService')
    @patch('mobile_api.job_detail.views.job_detail_view.resolve_job_detail_driver')
    def test_get_job_detail_304_not_modified(self, mock_resolve, mock_svc_cls):
        driver = _driver()
        mock_resolve.return_value = (driver, None, None)
        context = _shipment_context(driver)

        mock_svc_cls.return_value.resolve_job_detail.return_value = (
            JobDetailResolveResult(
                context=context,
                etag='"same"',
                not_modified=True,
            )
        )

        request = self.factory.get(
            self.shipment_url,
            HTTP_IF_NONE_MATCH='"same"',
        )
        force_authenticate(
            request,
            user=MobileUser(_jwt_payload(driver_id=driver.driver_id)),
            token=_jwt_payload(driver_id=driver.driver_id),
        )
        response = JobDetailAPIView.as_view()(
            request,
            job_type='shipment',
            job_id=str(context.job_id),
        )
        self.assertEqual(response.status_code, 304)


class JobDetailRBACTests(SimpleTestCase):
    def test_driver_has_job_detail_capability(self):
        request = MagicMock()
        request.auth = _jwt_payload()
        self.assertTrue(
            request_has_capability(request, 'mobile.driver.job_detail')
        )

    def test_dispatcher_lacks_job_detail_capability(self):
        request = MagicMock()
        request.auth = {
            **_jwt_payload(),
            'driver_id': '',
            'role_name': 'Dispatcher',
        }
        self.assertFalse(
            request_has_capability(request, 'mobile.driver.job_detail')
        )


class JobDetailTenantTests(SimpleTestCase):
    @patch(
        'mobile_api.job_detail.services.job_detail_context_service.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.shipment_job_resolver.lookup_shipment_by_reference',
    )
    def test_resolve_uses_tenant_schema(
        self,
        mock_lookup,
        mock_ship_schema,
        mock_ctx_schema,
    ):
        mock_ship_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_ship_schema.return_value.__exit__ = MagicMock(return_value=False)
        mock_ctx_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_ctx_schema.return_value.__exit__ = MagicMock(return_value=False)

        from tenant_workspace.models import DriverMaster

        driver = _driver()
        driver.driver_status = DriverMaster.Status.ACTIVE
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_no = 'SH-1'
        shipment.shipment_status = TenantShipment.ShipmentStatus.LOADED
        shipment.booking_item_type = 'Outbound'
        shipment.driver_id = driver.pk
        shipment.booking = None
        mock_lookup.return_value = shipment

        with patch(
            'mobile_api.job_detail.services.job_detail_context_service.load_projection_cache',
        ), patch(
            'mobile_api.job_detail.services.job_detail_context_service.reconcile_job_detail_entities',
        ), patch(
            'mobile_api.job_detail.services.job_detail_context_service.JobDetailProjectionService',
        ) as mock_proj_cls, patch(
            'mobile_api.job_detail.services.job_detail_context_service.finalize_job_detail_sync',
        ):
            mock_proj_cls.return_value.apply_projections.return_value = None
            JobDetailContextService().resolve_job_detail_context(
                driver,
                'shipment',
                str(shipment.pk),
                tenant_schema='tenant_xyz',
            )

        mock_ctx_schema.assert_called_with('tenant_xyz')
        mock_ship_schema.assert_called_with('tenant_xyz')


class JobDetailOrchestrationTests(SimpleTestCase):
    @patch(
        'mobile_api.job_detail.services.job_detail_context_service.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.job_detail_context_service.ShipmentJobResolver',
    )
    def test_context_service_raises_on_resolver_failure(
        self, mock_resolver_cls, mock_schema
    ):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)

        from mobile_api.job_detail.services.shipment_job_resolver import (
            ShipmentJobResolveResult,
        )

        mock_resolver_cls.return_value.resolve.return_value = ShipmentJobResolveResult(
            shipment=None,
            booking=None,
            error_code='job_not_found',
            error_message='missing',
        )

        with self.assertRaises(JobDetailError):
            JobDetailContextService().resolve_job_detail_context(
                _driver(),
                'shipment',
                str(uuid4()),
                tenant_schema='tenant_a',
            )
