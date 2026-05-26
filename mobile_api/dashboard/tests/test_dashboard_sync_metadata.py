"""
Tests for dashboard offline sync metadata and content hashing.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.services import dashboard_etag_service as etag_svc
from mobile_api.dashboard.services.dashboard_sync_metadata import (
    build_driver_dashboard_sync_metadata,
    build_entity_versions,
    resolve_content_hash,
)


def _ctx(**kwargs) -> DriverDashboardContext:
    defaults = {
        'driver': MagicMock(),
        'tenant_schema': 'tenant_a',
        'user_id': 'user-1',
    }
    defaults.update(kwargs)
    return DriverDashboardContext(**defaults)


class SyncMetadataContractTests(SimpleTestCase):
    def test_sync_metadata_required_fields(self):
        ctx = _ctx(
            workflow_projection={
                'current_stage': 'Pickup',
                'next_action': {'action_code': 'PICKUP'},
                'primary_action': {'action_code': 'PICKUP'},
                'allowed_actions': [{'action_code': 'PICKUP'}],
                'workflow_source': 'operation_execution.get_allowed_actions',
            },
            pod_cod_projection={'pod_pending': True, 'cod_pending': False},
            latest_action_log_id='log-42',
            content_hash='abc123',
        )
        meta = build_driver_dashboard_sync_metadata(ctx)

        self.assertEqual(meta['dashboard_projection_version'], '2')
        self.assertIn('workflow_integrity', meta)
        self.assertIn('compliance_integrity', meta)
        self.assertTrue(meta['generated_at'])
        self.assertEqual(meta['last_action_log_id'], 'log-42')
        self.assertEqual(meta['content_hash'], 'abc123')
        self.assertTrue(meta['workflow_version'])
        self.assertTrue(meta['server_time'])
        self.assertIn('booking', meta['entity_versions'])
        self.assertIn('shipment', meta['entity_versions'])
        self.assertIn('movement', meta['entity_versions'])
        self.assertIn('action_log', meta['entity_versions'])
        self.assertIn('pod_cod', meta['entity_versions'])


class ContentHashStabilityTests(SimpleTestCase):
    def test_stable_hash_when_inputs_unchanged(self):
        ctx = _ctx(
            workflow_projection={
                'current_stage': 'X',
                'next_action': {'action_code': 'A1'},
                'allowed_actions': [{'action_code': 'A1'}],
            },
            latest_action_log_id='log-1',
            pod_cod_projection={'pod_pending': False},
        )
        h1 = resolve_content_hash(ctx)
        ctx.content_hash = ''
        h2 = resolve_content_hash(ctx)
        self.assertEqual(h1, h2)
        self.assertTrue(len(h1) == 64)

    def test_identical_fingerprint_digest_is_deterministic(self):
        ctx = _ctx()
        fp1 = etag_svc.build_content_fingerprint(ctx, latest_action_log_id='1')
        fp2 = etag_svc.build_content_fingerprint(ctx, latest_action_log_id='1')
        self.assertEqual(etag_svc.fingerprint_digest(fp1), etag_svc.fingerprint_digest(fp2))


class ContentHashChangeTests(SimpleTestCase):
    def test_action_log_change_updates_hash_and_metadata(self):
        ctx = _ctx(
            workflow_projection={'current_stage': '', 'allowed_actions': []},
        )
        fp_a = etag_svc.fingerprint_digest(
            etag_svc.build_content_fingerprint(ctx, latest_action_log_id='log-a')
        )
        fp_b = etag_svc.fingerprint_digest(
            etag_svc.build_content_fingerprint(ctx, latest_action_log_id='log-b')
        )
        self.assertNotEqual(fp_a, fp_b)

        ctx.latest_action_log_id = 'log-a'
        meta_a = build_driver_dashboard_sync_metadata(ctx)
        ctx.latest_action_log_id = 'log-b'
        ctx.content_hash = ''
        meta_b = build_driver_dashboard_sync_metadata(ctx)
        self.assertNotEqual(meta_a['content_hash'], meta_b['content_hash'])
        self.assertEqual(meta_a['entity_versions']['action_log'], 'log-a')
        self.assertEqual(meta_b['entity_versions']['action_log'], 'log-b')

    def test_movement_change_updates_hash_and_entity_version(self):
        movement = types.SimpleNamespace(pk='m1', status='Scheduled')
        ctx = _ctx(active_empty_movement=movement)
        h1 = etag_svc.fingerprint_digest(
            etag_svc.build_content_fingerprint(ctx, latest_action_log_id='')
        )
        movement.status = 'In Progress'
        h2 = etag_svc.fingerprint_digest(
            etag_svc.build_content_fingerprint(ctx, latest_action_log_id='')
        )
        self.assertNotEqual(h1, h2)

        movement.status = 'Scheduled'
        ctx.content_hash = ''
        v_scheduled = build_entity_versions(ctx)['movement']
        movement.status = 'In Progress'
        ctx.content_hash = ''
        v_in_progress = build_entity_versions(ctx)['movement']
        self.assertNotEqual(v_scheduled, v_in_progress)

    def test_pod_cod_change_updates_hash_and_entity_version(self):
        ctx = _ctx(
            pod_cod_projection={
                'pod_pending': True,
                'pod_compliant': False,
                'hard_pod_pending': False,
                'cod_pending': False,
                'cod_collected': False,
                'treasury_pending': False,
                'delivery_blocked': False,
            },
        )
        h1 = etag_svc.fingerprint_digest(
            etag_svc.build_content_fingerprint(
                ctx,
                latest_action_log_id='',
                pod_cod=ctx.pod_cod_projection,
            )
        )
        ctx.pod_cod_projection = dict(ctx.pod_cod_projection, cod_pending=True)
        h2 = etag_svc.fingerprint_digest(
            etag_svc.build_content_fingerprint(
                ctx,
                latest_action_log_id='',
                pod_cod=ctx.pod_cod_projection,
            )
        )
        self.assertNotEqual(h1, h2)

        ctx.content_hash = ''
        v1 = build_entity_versions(ctx)['pod_cod']
        ctx.pod_cod_projection['cod_pending'] = False
        ctx.content_hash = ''
        v2 = build_entity_versions(ctx)['pod_cod']
        self.assertNotEqual(v1, v2)

    def test_next_action_change_updates_hash_and_workflow_version(self):
        ctx = _ctx(
            workflow_projection={
                'current_stage': 'Pickup',
                'next_action': {'action_code': 'PICKUP'},
                'primary_action': {'action_code': 'PICKUP'},
                'allowed_actions': [{'action_code': 'PICKUP'}],
            },
        )
        meta_a = build_driver_dashboard_sync_metadata(ctx)
        ctx.workflow_projection = {
            'current_stage': 'Pickup',
            'next_action': {'action_code': 'DELIVER'},
            'primary_action': {'action_code': 'DELIVER'},
            'allowed_actions': [{'action_code': 'DELIVER'}],
        }
        ctx.content_hash = ''
        meta_b = build_driver_dashboard_sync_metadata(ctx)
        self.assertNotEqual(meta_a['content_hash'], meta_b['content_hash'])
        self.assertNotEqual(meta_a['workflow_version'], meta_b['workflow_version'])

    def test_workflow_allowed_set_change_updates_hash(self):
        ctx = _ctx(
            workflow_projection={
                'current_stage': 'X',
                'next_action': {'action_code': 'A'},
                'allowed_actions': [{'action_code': 'A'}],
            },
        )
        h1 = etag_svc.fingerprint_digest(
            etag_svc.build_content_fingerprint(ctx, latest_action_log_id='')
        )
        ctx.workflow_projection['allowed_actions'] = [
            {'action_code': 'A'},
            {'action_code': 'B'},
        ]
        h2 = etag_svc.fingerprint_digest(
            etag_svc.build_content_fingerprint(ctx, latest_action_log_id='')
        )
        self.assertNotEqual(h1, h2)
