"""
API integration tests for POST execute action (mocked orchestrator / auth).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from mobile_api.authentication import MobileUser
from mobile_api.execution.dto.execute_action_result import ExecuteActionResult
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.views.execute_action_view import ExecuteActionAPIView
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


def _execute_payload(**overrides):
    base = {
        'client_action_id': str(uuid4()),
        'workflow_version': 'wf-pre',
        'content_hash': 'hash-pre',
        'latitude': 25.0,
        'longitude': 55.0,
        'notes': 'execute ok',
        'media': [],
    }
    base.update(overrides)
    return base


def _success_result(*, reused=False):
    return ExecuteActionResult(
        payload={
            'execution': {
                'job_type': 'shipment',
                'job_id': 'ship-1',
                'action_code': 'A2',
                'reused_existing': reused,
                'idempotent_replay': reused,
                'action_log_id': str(uuid4()),
                'log_no': 'OAL-001',
                'log_date': None,
                'idempotency_key': 'client-1',
            },
            'workflow': {
                'current_stage': 'In Transit',
                'next_action': {'action_code': 'A3'},
                'primary_action': {'action_code': 'A3'},
                'allowed_actions': [{'action_code': 'A3'}],
            },
            'pod_cod': {'pod_pending': True},
            'timeline_preview': {
                'scope': 'shipment',
                'timeline_preview': [{'event_id': 'e-new'}],
                'timeline_cursor': '',
                'has_more': False,
            },
            'sync_metadata': {
                'content_hash': 'hash-post',
                'workflow_version': 'wf-post',
                'entity_versions': {'shipment': 'v2'},
            },
            'alerts': {},
            'next_action_hint': {
                'action': 'execute_action',
                'screen': 'job_detail',
                'action_code': 'A3',
                'reason': 'Execute A3',
                'job_closed': False,
                'show_completion_screen': False,
            },
        },
        http_status=200 if reused else 201,
    )


class ExecuteActionAPITests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ExecuteActionAPIView.as_view()

    def _request(
        self,
        job_type='shipment',
        job_id=None,
        action_code='A2',
        *,
        data=None,
        jwt_payload=None,
    ):
        job_id = job_id or str(uuid4())
        driver = _driver()
        payload = jwt_payload or _jwt_payload(driver_id=driver.pk)
        url = reverse(
            'mobile_api:driver_execute_action',
            kwargs={
                'job_type': job_type,
                'job_id': job_id,
                'action_code': action_code,
            },
        )
        request = self.factory.post(
            url,
            data=data or _execute_payload(),
            format='json',
            HTTP_AUTHORIZATION='Bearer test-token',
            HTTP_X_TENANT_ID=payload.get('tenant_schema', 'tenant_test'),
        )
        force_authenticate(request, user=MobileUser(payload), token=payload)
        return request, job_id, driver, payload

    @patch('mobile_api.execution.views.execute_action_view.resolve_mobile_driver_session')
    @patch('mobile_api.execution.views.execute_action_view.tenant_schema_for_request')
    @patch('mobile_api.execution.views.execute_action_view.ExecuteActionOrchestrator')
    def test_shipment_execute_success_contract(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ):
        request, job_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        mock_orch_cls.return_value.execute_driver_action.return_value = _success_result()
        response = self.view(
            request,
            job_type='shipment',
            job_id=job_id,
            action_code='A2',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 1)
        data = response.data['data']
        self.assertEqual(
            set(data.keys()),
            {
                'execution',
                'workflow',
                'pod_cod',
                'timeline_preview',
                'sync_metadata',
                'alerts',
                'next_action_hint',
            },
        )
        self.assertIn('allowed_actions', data['workflow'])
        self.assertIn('timeline_preview', data['timeline_preview'])

    @patch('mobile_api.execution.views.execute_action_view.resolve_mobile_driver_session')
    @patch('mobile_api.execution.views.execute_action_view.tenant_schema_for_request')
    @patch('mobile_api.execution.views.execute_action_view.ExecuteActionOrchestrator')
    def test_movement_execute_omits_pod_cod(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ):
        request, job_id, driver, _payload = self._request(
            job_type='movement',
            action_code='M1',
        )
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        result = _success_result()
        result.payload['pod_cod'] = {}
        result.payload['execution']['job_type'] = 'movement'
        mock_orch_cls.return_value.execute_driver_action.return_value = result
        response = self.view(
            request,
            job_type='movement',
            job_id=job_id,
            action_code='M1',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['data']['pod_cod'], {})

    @patch('mobile_api.execution.views.execute_action_view.resolve_mobile_driver_session')
    @patch('mobile_api.execution.views.execute_action_view.tenant_schema_for_request')
    def test_tenant_required(self, mock_tenant_schema, mock_resolve_session):
        request, job_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = ''
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        response = self.view(
            request,
            job_type='shipment',
            job_id=job_id,
            action_code='A2',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['data']['error_code'], 'tenant_required')

    @patch('mobile_api.execution.views.execute_action_view.resolve_mobile_driver_session')
    @patch('mobile_api.execution.views.execute_action_view.tenant_schema_for_request')
    @patch('mobile_api.execution.views.execute_action_view.ExecuteActionOrchestrator')
    def test_stale_execute_returns_409(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ):
        request, job_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        mock_orch_cls.return_value.execute_driver_action.side_effect = ExecuteActionError(
            'stale',
            code='stale_content_hash',
            http_status=409,
            refresh_required=True,
        )
        response = self.view(
            request,
            job_type='shipment',
            job_id=job_id,
            action_code='A2',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['data']['error_code'], 'stale_content_hash')
        self.assertTrue(response.data['data'].get('refresh_required'))

    @patch('mobile_api.execution.views.execute_action_view.resolve_mobile_driver_session')
    @patch('mobile_api.execution.views.execute_action_view.tenant_schema_for_request')
    @patch('mobile_api.execution.views.execute_action_view.ExecuteActionOrchestrator')
    def test_idempotency_replay_returns_200(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ):
        request, job_id, driver, _payload = self._request()
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        mock_orch_cls.return_value.execute_driver_action.return_value = _success_result(
            reused=True,
        )
        response = self.view(
            request,
            job_type='shipment',
            job_id=job_id,
            action_code='A2',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['data']['execution']['reused_existing'])

    def test_missing_client_action_id_400(self):
        request, job_id, _driver, _payload = self._request(
            data={
                'workflow_version': 'wf',
                'content_hash': 'h',
                'latitude': 1.0,
                'longitude': 2.0,
                'notes': '',
                'media': [],
            },
        )
        response = self.view(
            request,
            job_type='shipment',
            job_id=job_id,
            action_code='A2',
        )
        self.assertEqual(response.status_code, 400)

    @patch('mobile_api.execution.views.execute_action_view.resolve_mobile_driver_session')
    @patch('mobile_api.execution.views.execute_action_view.tenant_schema_for_request')
    @patch('mobile_api.execution.views.execute_action_view.ExecuteActionOrchestrator')
    def test_media_passed_to_orchestrator(
        self,
        mock_orch_cls,
        mock_tenant_schema,
        mock_resolve_session,
    ):
        request, job_id, driver, _payload = self._request(
            data=_execute_payload(
                media=[{'media_type': 'photo', 'file_ref': 'path/x.jpg'}],
            ),
        )
        mock_tenant_schema.return_value = 'tenant_test'
        mock_resolve_session.return_value = (MagicMock(), driver, None, None)
        mock_orch_cls.return_value.execute_driver_action.return_value = _success_result()
        response = self.view(
            request,
            job_type='shipment',
            job_id=job_id,
            action_code='A2',
        )
        self.assertEqual(response.status_code, 201)
        call_payload = mock_orch_cls.return_value.execute_driver_action.call_args.kwargs[
            'payload'
        ]
        self.assertEqual(len(call_payload['media']), 1)


class ExecuteActionRBACTests(SimpleTestCase):
    def test_driver_has_execute_capability(self):
        request = MagicMock()
        request.auth = _jwt_payload()
        self.assertTrue(
            request_has_capability(request, 'mobile.driver.execute'),
        )

    def test_dispatcher_lacks_execute_capability(self):
        request = MagicMock()
        request.auth = {
            **_jwt_payload(),
            'driver_id': '',
            'role_name': 'Dispatcher',
        }
        self.assertFalse(
            request_has_capability(request, 'mobile.driver.execute'),
        )


class ExecuteActionStaleGuardTests(SimpleTestCase):
    def test_stale_guard_accepts_content_hash_field(self):
        from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
        from mobile_api.execution.guards.stale_execution_guard import StaleExecutionGuard

        ctx = ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='shipment',
            job_id='s1',
            action_code='A2',
            payload={
                'content_hash': 'wrong',
                'workflow_version': 'wf-server',
            },
            sync_metadata={'content_hash': 'server-hash'},
        )
        with self.assertRaises(ExecuteActionError) as exc:
            StaleExecutionGuard().assert_not_stale(ctx)
        self.assertEqual(exc.exception.code, 'stale_content_hash')
