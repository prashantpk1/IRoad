"""History milestone matching for renamed Action Master codes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from datetime import datetime, timezone

from mobile_api.history.projections.history_milestone_resolver import (
    infer_milestone_completion_from_shipment,
    milestone_completed_for_history,
    pick_log_for_history_milestone,
    resolve_history_milestone_specs,
)
from tenant_workspace.models import TenantShipment


def _log(action_code: str, *, log_date=None, **action_kwargs):
    action = SimpleNamespace(
        action_code=action_code,
        english_label=action_kwargs.get('english_label', action_code),
        arabic_label='',
        shipment_status_impact=action_kwargs.get('shipment_status_impact', ''),
        movement_status_impact='',
        auto_pod_post=action_kwargs.get('auto_pod_post', False),
        auto_treasury_post=action_kwargs.get('auto_treasury_post', False),
        sequence_category=action_kwargs.get('sequence_category', ''),
    )
    return SimpleNamespace(
        operation_action=action,
        log_date=log_date,
        created_at=log_date,
        media_rows=MagicMock(all=MagicMock(return_value=[])),
    )


class HistoryMilestoneResolverTests(SimpleTestCase):
    def test_cod_specs_include_payment(self):
        specs = resolve_history_milestone_specs(order_type='COD', tenant_schema='')
        keys = [row[0] for row in specs]
        self.assertIn('payment', keys)
        self.assertIn('job_closed', keys)

    def test_credit_specs_skip_payment(self):
        specs = resolve_history_milestone_specs(order_type='Credit', tenant_schema='')
        keys = [row[0] for row in specs]
        self.assertNotIn('payment', keys)
        self.assertIn('job_closed', keys)

    def test_pick_log_matches_renamed_collect_payment(self):
        log = _log('OA-0009', auto_treasury_post=True, english_label='Collect Payment')
        row = pick_log_for_history_milestone(
            [log],
            step_key='payment',
            action_codes=('OA-0009',),
        )
        self.assertIs(row, log)

    def test_pick_log_matches_job_close_by_impact(self):
        log = _log(
            'OA-0010',
            shipment_status_impact='Closed',
            english_label='Job Closed',
        )
        row = pick_log_for_history_milestone(
            [log],
            step_key='job_closed',
            action_codes=('OA-0010',),
        )
        self.assertIs(row, log)

    def test_infer_job_closed_from_shipment_column(self):
        shipment = SimpleNamespace(
            shipment_status=TenantShipment.ShipmentStatus.CLOSED,
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.COLLECTED,
            pod_status='Completed',
        )
        self.assertTrue(
            infer_milestone_completion_from_shipment(shipment, 'job_closed'),
        )

    def test_closed_shipment_marks_all_milestones_completed_without_logs(self):
        shipment = SimpleNamespace(
            shipment_status=TenantShipment.ShipmentStatus.CLOSED,
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.COLLECTED,
            pod_status=TenantShipment.PodStatus.COMPLETED,
        )
        for step_key in (
            'pickup',
            'loading',
            'in_transit',
            'delivery',
            'pod',
            'unloading',
            'payment',
            'job_closed',
        ):
            self.assertTrue(
                milestone_completed_for_history(
                    shipment,
                    step_key,
                    None,
                    order_type='COD',
                ),
                step_key,
            )

    def test_loading_picks_earliest_log_for_timestamp(self):
        t_early = datetime(2026, 6, 24, 15, 1, tzinfo=timezone.utc)
        t_late = datetime(2026, 6, 24, 15, 3, tzinfo=timezone.utc)
        a3 = _log('OA-0003', log_date=t_early, english_label='Start Loading')
        a4 = _log('OA-0004', log_date=t_late, english_label='Confirm Loaded')
        row = pick_log_for_history_milestone(
            [a4, a3],
            step_key='loading',
            action_codes=('OA-0003', 'OA-0004'),
        )
        self.assertIs(row, a3)

    def test_payment_infer_uses_resolved_order_type(self):
        shipment = SimpleNamespace(
            shipment_status=TenantShipment.ShipmentStatus.CLOSED,
            order_type='',
            collection_status=TenantShipment.CollectionStatus.COLLECTED,
            pod_status=TenantShipment.PodStatus.COMPLETED,
        )
        self.assertTrue(
            infer_milestone_completion_from_shipment(
                shipment,
                'payment',
                order_type='COD',
            ),
        )
