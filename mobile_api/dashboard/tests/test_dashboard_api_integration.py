"""
Integration-style tests for GET /api/v1/mobile/driver/dashboard/.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from mobile_api.authentication import MobileUser
from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.dto.dashboard_resolve_result import (
    DashboardResolveResult,
)
from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.dto.driver_empty_move_selection import (
    DriverEmptyMoveSelectionResult,
)
from mobile_api.dashboard.services.dashboard_context_service import (
    DashboardContextService,
)
from mobile_api.dashboard.views.dashboard_view import DashboardAPIView
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


def _full_context(driver):
    shipment = MagicMock()
    shipment.pk = uuid4()
    shipment.shipment_id = shipment.pk
    shipment.driver_id = driver.pk
    booking = MagicMock()
    booking.pk = uuid4()
    booking.booking_id = booking.pk
    booking_selection = DriverBookingSelectionResult(
        booking=booking,
        active_shipment=shipment,
        next_executable_shipment=shipment,
        shipments_total=1,
        shipments_completed=0,
        progress_percentage=0,
    )
    movement = MagicMock()
    movement.pk = uuid4()
    movement.movement_id = movement.pk
    movement.driver_id = driver.pk
    empty_selection = DriverEmptyMoveSelectionResult(
        movement=movement,
        movement_stage='created',
        movement_status=TenantTruckMovementLog.Status.SCHEDULED,
        progress_percentage=10,
    )
    return DriverDashboardContext(
        driver=driver,
        tenant_schema='tenant_test',
        user_id=str(uuid4()),
        active_booking=booking,
        active_shipment=shipment,
        booking_selection=booking_selection,
        active_empty_movement=movement,
        empty_move_selection=empty_selection,
        booking_projection={
            'booking_id': str(booking.pk),
            'booking_no': 'BK-1',
            'trip_type': 'One-Way',
            'shipments_total': 1,
            'shipments_completed': 0,
            'active_shipment': {'shipment_no': 'SH-1'},
            'progress_percentage': 0,
        },
        movement_projection={
            'movement_id': str(movement.pk),
            'movement_no': 'EM-1',
            'movement_stage': 'created',
            'movement_status': 'Scheduled',
            'progress_percentage': 10,
        },
        workflow_projection={
            'current_stage': 'Pickup',
            'next_action': {'action_code': 'A2'},
            'primary_action': {'action_code': 'A2'},
            'allowed_actions': [{'action_code': 'A2'}],
            'workflow_source': 'operation_execution.get_allowed_actions',
        },
        pod_cod_projection={
            'pod_pending': True,
            'pod_compliant': False,
            'hard_pod_pending': False,
            'cod_pending': False,
            'cod_collected': False,
            'treasury_pending': False,
            'delivery_blocked': False,
        },
        summary={
            'timeline_summary': {
                'scope': 'shipment',
                'recent_count': 1,
                'recent_events': [],
                'has_more': False,
            },
            'alerts': {'count': 1, 'items': [{'code': 'pod_pending'}]},
        },
        sync_metadata={'generated_at': '2026-05-26T00:00:00+00:00'},
    )


class DashboardAPIIntegrationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.url = reverse('mobile_api:driver_dashboard')

    @patch('mobile_api.dashboard.views.dashboard_view.DashboardContextService')
    @patch('mobile_api.dashboard.views.dashboard_view.resolve_dashboard_driver')
    def test_get_dashboard_success_envelope(self, mock_resolve, mock_svc_cls):
        driver = _driver()
        mock_resolve.return_value = (driver, None, None)
        context = _full_context(driver)

        mock_svc = mock_svc_cls.return_value
        mock_svc.resolve_driver_dashboard.return_value = DashboardResolveResult(
            context=context,
            etag='',
            not_modified=False,
        )
        mock_svc.build_api_payload.return_value = {
            'current_job': context.booking_projection,
            'current_empty_move': context.movement_projection,
            'workflow': context.workflow_projection,
            'pod_cod_summary': context.pod_cod_projection,
            'timeline_summary': context.summary['timeline_summary'],
            'alerts': context.summary['alerts'],
            'sync_metadata': context.sync_metadata,
        }

        request = self.factory.get(self.url)
        payload = _jwt_payload(driver_id=driver.driver_id)
        force_authenticate(
            request,
            user=MobileUser(payload),
            token=payload,
        )
        response = DashboardAPIView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        body = response.data
        self.assertEqual(body['status'], 1)
        data = body['data']
        self.assertEqual(data['current_job']['booking_no'], 'BK-1')
        self.assertEqual(data['current_empty_move']['movement_no'], 'EM-1')
        self.assertEqual(data['workflow']['current_stage'], 'Pickup')
        self.assertTrue(data['pod_cod_summary']['pod_pending'])
        self.assertEqual(data['timeline_summary']['scope'], 'shipment')
        self.assertEqual(data['alerts']['count'], 1)

    @patch('mobile_api.dashboard.views.dashboard_view.resolve_dashboard_driver')
    def test_get_dashboard_auth_failure(self, mock_resolve):
        mock_resolve.return_value = (None, 'Unauthorized', 'unauthorized')
        request = self.factory.get(self.url)
        force_authenticate(
            request,
            user=MobileUser(_jwt_payload()),
            token=_jwt_payload(),
        )
        response = DashboardAPIView.as_view()(request)
        self.assertEqual(response.status_code, 401)

    @patch('mobile_api.dashboard.views.dashboard_view.DashboardContextService')
    @patch('mobile_api.dashboard.views.dashboard_view.resolve_dashboard_driver')
    def test_get_dashboard_ownership_forbidden(self, mock_resolve, mock_svc_cls):
        from django.core.exceptions import PermissionDenied

        driver = _driver()
        mock_resolve.return_value = (driver, None, None)
        mock_svc_cls.return_value.resolve_driver_dashboard.side_effect = (
            PermissionDenied()
        )

        request = self.factory.get(self.url)
        force_authenticate(
            request,
            user=MobileUser(_jwt_payload(driver_id=driver.driver_id)),
            token=_jwt_payload(driver_id=driver.driver_id),
        )
        response = DashboardAPIView.as_view()(request)

        self.assertEqual(response.status_code, 403)


class DashboardContextOrchestrationTests(SimpleTestCase):
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.get_cached_projections',
        return_value=None,
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.load_projection_cache',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.reconcile_dashboard_entities',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.apply_reconciled_status_overlays',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.DashboardSummaryService',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.build_pod_cod_summary_for_context',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.build_workflow_for_dashboard_context',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.build_booking_card_from_selection',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.assert_dashboard_scope_ownership',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.DashboardMovementSelector',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.DashboardBookingSelector',
    )
    def test_orchestration_wires_selectors_and_projections(
        self,
        mock_booking_cls,
        mock_movement_cls,
        _mock_assert,
        mock_booking_card,
        mock_workflow,
        mock_pod,
        mock_summary_cls,
        mock_overlay,
        mock_reconcile_entities,
        _mock_load_cache,
        _mock_cache,
    ):
        from contextlib import nullcontext

        mock_overlay.side_effect = lambda _ctx: nullcontext()

        def _recon(ctx, *, request=None, projection_cache=None):
            ctx.reconciliation = {
                'workflow_reconciled': True,
                'any_drift': False,
                'shipment': None,
                'movement': None,
                'pod_cod': {},
                'pod_cod_flags': {},
                'reconciliation_version': 'r1',
                'compliance_projection_version': 'c1',
                'workflow_integrity': {},
            }

        mock_reconcile_entities.side_effect = _recon
        driver = _driver()
        booking = MagicMock()
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.driver_id = driver.pk
        movement = MagicMock()
        movement.pk = uuid4()
        movement.driver_id = driver.pk

        booking_sel = DriverBookingSelectionResult(
            booking=booking,
            active_shipment=shipment,
            next_executable_shipment=shipment,
        )
        empty_sel = DriverEmptyMoveSelectionResult(
            movement=movement,
            movement_stage='created',
            movement_status='Scheduled',
            progress_percentage=10,
        )

        mock_booking_cls.return_value.select_current_driver_booking.return_value = (
            booking_sel
        )
        mock_movement_cls.return_value.select_current_empty_move.return_value = (
            empty_sel
        )
        mock_booking_card.return_value = {'booking_no': 'BK-99'}
        mock_workflow.return_value = {'current_stage': 'Pickup'}
        mock_pod.return_value = {'pod_pending': True}
        mock_summary_cls.return_value.build_summary.return_value = {
            'timeline_summary': {},
            'alerts': {'count': 1, 'items': []},
        }
        mock_summary_cls.return_value.build_sync_metadata.return_value = {
            'generated_at': '2026-01-01T00:00:00+00:00',
        }

        ctx = DashboardContextService(
            booking_selector=mock_booking_cls.return_value,
            movement_selector=mock_movement_cls.return_value,
            summary_service=mock_summary_cls.return_value,
        ).resolve_driver_dashboard_context(
            driver,
            tenant_schema='tenant_a',
            user_id='u1',
        )

        self.assertIs(ctx.active_booking, booking)
        self.assertIs(ctx.active_empty_movement, movement)
        mock_workflow.assert_called_once()
        mock_pod.assert_called_once()
        mock_movement_cls.return_value.select_current_empty_move.assert_called_once()

    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.get_cached_projections',
        return_value=None,
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.load_projection_cache',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.reconcile_dashboard_entities',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.apply_reconciled_status_overlays',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.DashboardSummaryService',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.DashboardMovementSelector',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.DashboardBookingSelector',
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.build_workflow_for_dashboard_context',
        return_value={},
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.build_pod_cod_summary_for_context',
        return_value={},
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.build_booking_card_from_selection',
        return_value={},
    )
    @patch(
        'mobile_api.dashboard.services.dashboard_context_service.assert_dashboard_scope_ownership',
    )
    def test_idle_driver_empty_payload(
        self,
        _mock_assert,
        _mock_card,
        _mock_pod,
        _mock_wf,
        mock_movement_cls,
        mock_booking_cls,
        mock_summary_cls,
        mock_overlay,
        mock_reconcile_entities,
        _mock_load_cache,
        _mock_cache,
    ):
        from contextlib import nullcontext

        mock_overlay.side_effect = lambda _ctx: nullcontext()

        def _recon(ctx, *, request=None, projection_cache=None):
            ctx.reconciliation = {
                'workflow_reconciled': True,
                'any_drift': False,
                'shipment': None,
                'movement': None,
                'pod_cod': {},
                'pod_cod_flags': {},
                'reconciliation_version': 'r1',
                'compliance_projection_version': 'c1',
                'workflow_integrity': {},
            }

        mock_reconcile_entities.side_effect = _recon
        mock_booking_cls.return_value.select_current_driver_booking.return_value = None
        mock_movement_cls.return_value.select_current_empty_move.return_value = None
        mock_summary_cls.return_value.build_summary.return_value = {
            'timeline_summary': {},
            'alerts': {'count': 0, 'items': []},
        }
        mock_summary_cls.return_value.build_sync_metadata.return_value = {}
        driver = _driver()
        ctx = DashboardContextService(
            booking_selector=mock_booking_cls.return_value,
            movement_selector=mock_movement_cls.return_value,
            summary_service=mock_summary_cls.return_value,
        ).resolve_driver_dashboard_context(
            driver,
            tenant_schema='tenant_a',
            user_id='u1',
        )
        payload = DashboardContextService().build_api_payload(ctx)
        self.assertEqual(payload['current_job'], {})
        self.assertEqual(payload['current_empty_move'], {})


class DashboardSecurityTests(SimpleTestCase):
    @patch('mobile_api.dashboard.services.driver_resolver.resolve_mobile_driver_session')
    @patch('mobile_api.dashboard.services.driver_resolver.has_driver_id_claim', return_value=True)
    def test_resolve_dashboard_driver_tenant_session(
        self, _mock_claim, mock_session
    ):
        driver = _driver()
        mock_session.return_value = (MagicMock(), driver, None, None)
        request = MagicMock()
        request.auth = _jwt_payload(schema='tenant_alpha')

        with patch(
            'mobile_api.dashboard.services.driver_resolver.get_mobile_jwt_payload',
            return_value=request.auth,
        ):
            from mobile_api.dashboard.services.driver_resolver import (
                resolve_dashboard_driver,
            )

            resolved, err, code = resolve_dashboard_driver(request)

        self.assertIs(resolved, driver)
        self.assertIsNone(err)
        mock_session.assert_called_once()

    def test_assert_ownership_rejects_foreign_movement(self):
        from django.core.exceptions import PermissionDenied
        from mobile_api.dashboard.services.driver_resolver import (
            assert_dashboard_scope_ownership,
        )

        driver = _driver()
        movement = MagicMock()
        movement.driver_id = uuid4()
        with self.assertRaises(PermissionDenied):
            assert_dashboard_scope_ownership(
                driver,
                active_movement=movement,
            )
