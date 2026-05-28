"""
Workflow projection tests — shipment/movement, reconcile, allowed actions.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase, TestCase

from mobile_api.dashboard.services.dashboard_status_reconciler import (
    INTEGRITY_DRIFT,
    INTEGRITY_MISSING_LOGS,
)
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.projections.workflow_projection import (
    build_workflow_section,
)
from mobile_api.job_detail.services.job_detail_projection_service import (
    JobDetailProjectionService,
)
from mobile_api.job_detail.services.job_detail_status_reconciler import (
    reconcile_job_detail_entities,
)
from tenant_workspace.models import TenantTruckMovementLog


def _action_row(code='A1', label='Start', *, sort_index=0):
    return {
        'action_id': str(uuid4()),
        'action_code': code,
        'action_name': label,
        'execution_label': label,
        'requires_gps': True,
        'requires_photo': False,
        'requires_video': False,
        'requires_note': False,
        'action_category': 'job',
        'execution_order': sort_index + 1,
        'sort_index': sort_index,
        'current_stage': 'Pickup',
        'execution_requirements': {
            'gps': True,
            'photo': False,
            'video': False,
            'note': False,
            'photo_min_count': 0,
        },
    }


def _engine_payload(*, actions=None, stage='Pickup', job_type='shipment'):
    rows = (
        list(actions)
        if actions is not None
        else [_action_row(), _action_row(code='A2', label='Load')]
    )
    primary = rows[0] if rows else None
    return {
        'job_type': job_type,
        'job_id': str(uuid4()),
        'job_no': 'JOB-1',
        'current_stage': stage,
        'context_label': 'test',
        'count': len(rows),
        'actions': rows,
        'primary_action': primary,
        'workflow_source': 'operation_execution.get_allowed_actions',
    }


def _driver():
    d = MagicMock()
    d.pk = uuid4()
    d.driver_id = d.pk
    return d


def _shipment(*, status='Loaded'):
    s = MagicMock()
    s.pk = uuid4()
    s.shipment_id = s.pk
    s.shipment_no = 'SH-100'
    s.shipment_status = status
    s.booking_item_type = 'Outbound'
    return s


def _movement():
    m = MagicMock()
    m.pk = uuid4()
    m.movement_id = m.pk
    m.movement_no = 'EM-50'
    m.status = TenantTruckMovementLog.Status.SCHEDULED
    m.movement_source = 'empty'
    return m


def _recon_block(
    *,
    auth='In Transit',
    column='Loaded',
    log_count=3,
    drift=False,
    reason='',
):
    from mobile_api.dashboard.services.dashboard_status_reconciler import (
        build_workflow_integrity,
    )

    wi = build_workflow_integrity(
        log_count=log_count,
        authoritative_status=auth,
        column_status=column,
        drift_detected=drift,
        status_source='action_logs' if log_count else 'columns_fallback',
    )
    return {
        'authoritative_status': auth,
        'column_status': column,
        'status_source': 'action_logs' if log_count else 'columns_fallback',
        'drift_detected': drift,
        'drift_reason': reason,
        'workflow_integrity': wi,
        'raw': {'timeline': {'log_count': log_count}},
    }


class JobDetailWorkflowProjectionTests(SimpleTestCase):
    @patch(
        'mobile_api.job_detail.projections.workflow_projection.derive_job_execution_stage',
    )
    @patch(
        'mobile_api.job_detail.projections.workflow_projection.OperationExecutionService.get_allowed_driver_actions',
    )
    @patch(
        'mobile_api.job_detail.projections.workflow_projection.apply_reconciled_status_overlays',
    )
    def test_shipment_workflow_primary_and_next_action(
        self, mock_overlay, mock_allowed, mock_stage
    ):
        mock_overlay.return_value.__enter__ = MagicMock(return_value=None)
        mock_overlay.return_value.__exit__ = MagicMock(return_value=False)
        mock_allowed.return_value = _engine_payload(stage='Pickup')
        mock_stage.return_value = {
            'entity_type': 'shipment',
            'execution_sub_stage': 'pickup',
            'operational_stage': 'Pickup',
            'status_for_workflow': 'In Transit',
        }

        shipment = _shipment()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
        )
        ctx.reconciliation = {
            'shipment': _recon_block(auth='In Transit', column='Loaded'),
            'workflow_integrity': _recon_block()['workflow_integrity'],
        }

        wf = build_workflow_section(ctx)

        self.assertEqual(wf['current_stage'], 'Pickup')
        self.assertEqual(len(wf['allowed_actions']), 2)
        self.assertEqual(wf['primary_action']['action_code'], 'A1')
        self.assertEqual(wf['next_action']['action_code'], 'A1')
        self.assertIn('execution_requirements', wf['allowed_actions'][0])
        self.assertEqual(
            wf['workflow_source'],
            'operation_execution.get_allowed_actions',
        )
        self.assertEqual(wf['reconciliation']['authoritative_status'], 'In Transit')
        self.assertTrue(wf['workflow_integrity'])

    @patch(
        'mobile_api.job_detail.projections.workflow_projection.derive_job_execution_stage',
    )
    @patch(
        'mobile_api.job_detail.projections.workflow_projection.OperationExecutionService.get_allowed_driver_actions',
    )
    @patch(
        'mobile_api.job_detail.projections.workflow_projection.apply_reconciled_status_overlays',
    )
    def test_movement_workflow(self, mock_overlay, mock_allowed, mock_stage):
        mock_overlay.return_value.__enter__ = MagicMock(return_value=None)
        mock_overlay.return_value.__exit__ = MagicMock(return_value=False)
        mock_allowed.return_value = _engine_payload(
            stage='Started',
            job_type='movement',
            actions=[_action_row(code='M1', label='Start Move')],
        )
        mock_stage.return_value = {
            'entity_type': 'movement',
            'execution_sub_stage': 'started',
            'operational_stage': 'Started',
            'status_for_workflow': 'In Progress',
        }

        movement = _movement()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='movement',
            job_id=str(movement.pk),
            movement=movement,
        )
        ctx.reconciliation = {
            'movement': _recon_block(auth='In Progress', column='Scheduled'),
            'workflow_integrity': _recon_block()['workflow_integrity'],
        }

        wf = build_workflow_section(ctx)

        self.assertEqual(wf['current_stage'], 'Started')
        self.assertEqual(wf['primary_action']['action_code'], 'M1')
        mock_allowed.assert_called_once()
        call_kw = mock_allowed.call_args.kwargs
        self.assertIs(call_kw.get('movement'), movement)
        self.assertIsNone(call_kw.get('shipment'))

    @patch(
        'mobile_api.job_detail.projections.workflow_projection.derive_job_execution_stage',
    )
    @patch(
        'mobile_api.job_detail.projections.workflow_projection.OperationExecutionService.get_allowed_driver_actions',
    )
    @patch(
        'mobile_api.job_detail.projections.workflow_projection.apply_reconciled_status_overlays',
    )
    def test_drift_surfaces_in_reconciliation(
        self, mock_overlay, mock_allowed, mock_stage
    ):
        mock_overlay.return_value.__enter__ = MagicMock(return_value=None)
        mock_overlay.return_value.__exit__ = MagicMock(return_value=False)
        mock_allowed.return_value = _engine_payload(actions=[_action_row()])
        mock_stage.return_value = {'operational_stage': 'In Transit'}

        shipment = _shipment()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
        )
        block = _recon_block(
            auth='In Transit',
            column='Loaded',
            drift=True,
            reason='column_behind_action_logs',
        )
        ctx.reconciliation = {
            'shipment': block,
            'workflow_integrity': {
                **block['workflow_integrity'],
                'workflow_integrity_state': INTEGRITY_DRIFT,
            },
            'any_drift': True,
        }

        wf = build_workflow_section(ctx)

        self.assertTrue(wf['reconciliation']['drift_detected'])
        self.assertEqual(
            wf['reconciliation']['drift_reason'],
            'column_behind_action_logs',
        )

    @patch(
        'mobile_api.job_detail.projections.workflow_projection.derive_job_execution_stage',
    )
    @patch(
        'mobile_api.job_detail.projections.workflow_projection.OperationExecutionService.get_allowed_driver_actions',
    )
    @patch(
        'mobile_api.job_detail.projections.workflow_projection.apply_reconciled_status_overlays',
    )
    def test_missing_logs_integrity(self, mock_overlay, mock_allowed, mock_stage):
        mock_overlay.return_value.__enter__ = MagicMock(return_value=None)
        mock_overlay.return_value.__exit__ = MagicMock(return_value=False)
        mock_allowed.return_value = _engine_payload(actions=[])
        mock_stage.return_value = {}

        shipment = _shipment()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
        )
        block = _recon_block(auth='Loaded', column='Loaded', log_count=0)
        ctx.reconciliation = {
            'shipment': block,
            'workflow_integrity': {
                **block['workflow_integrity'],
                'workflow_integrity_state': INTEGRITY_MISSING_LOGS,
                'missing_log_warning': True,
            },
        }

        wf = build_workflow_section(ctx)

        self.assertTrue(wf['workflow_integrity'].get('missing_log_warning'))
        self.assertEqual(wf['allowed_actions'], [])


class JobDetailReconcileIntegrationTests(SimpleTestCase):
    @patch(
        'mobile_api.job_detail.services.job_detail_status_reconciler.reconcile_shipment_execution_state',
    )
    @patch(
        'mobile_api.job_detail.services.job_detail_projection_cache.scoped_shipment_action_logs',
    )
    def test_reconcile_populates_bundle(self, mock_logs, mock_reconcile):
        mock_logs.return_value = [MagicMock(log_id=uuid4())]
        mock_reconcile.return_value = {
            'authoritative_status': 'In Transit',
            'column_status': 'Loaded',
            'shipment_status': 'Loaded',
            'timeline': {'log_count': 1},
            'drift': {'has_drift': True, 'reason': 'column_behind_action_logs'},
        }

        shipment = _shipment()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
            resolver_meta={'ownership_validated': True},
        )

        bundle = reconcile_job_detail_entities(ctx)

        self.assertTrue(bundle.get('workflow_reconciled'))
        self.assertTrue(bundle.get('any_drift'))
        self.assertIsNotNone(bundle.get('shipment'))
        self.assertTrue(ctx.reconciliation.get('workflow_integrity'))


class JobDetailProjectionServiceOrderTests(TestCase):
    @patch.object(JobDetailProjectionService, '_build_alerts_placeholder', return_value={})
    @patch('mobile_api.job_detail.services.job_detail_projection_service.build_sync_metadata')
    @patch('mobile_api.job_detail.services.job_detail_projection_service.build_round_trip_section')
    @patch('mobile_api.job_detail.services.job_detail_projection_service.build_pod_cod_section')
    @patch('mobile_api.job_detail.services.job_detail_projection_service.build_timeline_section')
    @patch('mobile_api.job_detail.services.job_detail_projection_service.build_job_header')
    @patch('mobile_api.job_detail.services.job_detail_projection_service.build_workflow_section')
    @patch(
        'mobile_api.job_detail.services.job_detail_projection_service.reconcile_job_detail_entities',
    )
    @patch(
        'mobile_api.job_detail.services.job_detail_projection_service.load_projection_cache',
    )
    def test_apply_projections_reconcile_before_workflow(
        self,
        mock_cache,
        mock_reconcile,
        mock_workflow,
        *_rest,
    ):
        shipment = _shipment()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
            resolver_meta={'ownership_validated': True},
        )
        call_order: list[str] = []

        def _cache(_ctx):
            call_order.append('cache')
            return MagicMock()

        def _reconcile(_ctx, **kwargs):
            call_order.append('reconcile')
            return {}

        def _workflow(_ctx, **kwargs):
            call_order.append('workflow')
            return {}

        mock_cache.side_effect = _cache
        mock_reconcile.side_effect = _reconcile
        mock_workflow.side_effect = _workflow

        JobDetailProjectionService().apply_projections(ctx)

        self.assertEqual(call_order[:3], ['cache', 'reconcile', 'workflow'])
