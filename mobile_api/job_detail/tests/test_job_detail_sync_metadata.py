"""
Sync metadata and content hashing for Job Detail.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.services.job_detail_etag_service import (
    build_content_fingerprint,
    fingerprint_digest,
)
from mobile_api.job_detail.services.job_detail_sync_metadata import (
    build_entity_versions,
    build_job_detail_sync_metadata,
    build_workflow_version,
    finalize_job_detail_sync,
    resolve_content_hash,
)


def _ctx(**kwargs) -> JobDetailContext:
    defaults = {
        'driver': MagicMock(),
        'tenant_schema': 'tenant_a',
        'user_id': 'user-1',
        'job_type': 'shipment',
        'job_id': str(uuid4()),
    }
    defaults.update(kwargs)
    return JobDetailContext(**defaults)


class JobDetailSyncMetadataTests(SimpleTestCase):
    def test_sync_metadata_required_fields(self):
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_id = shipment.pk
        shipment.shipment_status = 'Loaded'
        shipment.booking_item_type = 'Outbound'

        ctx = _ctx(
            shipment=shipment,
            workflow={
                'current_stage': 'Pickup',
                'next_action': {'action_code': 'A2'},
                'primary_action': {'action_code': 'A2'},
                'allowed_actions': [{'action_code': 'A2'}],
                'workflow_source': 'operation_execution.get_allowed_actions',
            },
            pod_cod={'pod_pending': True, 'cod_pending': False},
            latest_action_log_id='log-42',
            reconciliation={
                'reconciliation_version': 'rev1',
                'workflow_integrity': {'workflow_integrity_state': 'ok'},
                'compliance_integrity': {'compliance_drift': False},
            },
        )
        finalize_job_detail_sync(ctx)
        meta = ctx.sync_metadata

        self.assertTrue(meta['content_hash'])
        self.assertTrue(meta['workflow_version'])
        self.assertTrue(meta['generated_at'])
        self.assertEqual(meta['last_action_log_id'], 'log-42')
        self.assertIn('shipment', meta['entity_versions'])
        self.assertIn('action_log', meta['entity_versions'])

    def test_stable_content_hash(self):
        ctx = _ctx(
            workflow={'current_stage': 'X', 'allowed_actions': []},
            latest_action_log_id='log-1',
        )
        h1 = resolve_content_hash(ctx)
        ctx.content_hash = ''
        h2 = resolve_content_hash(ctx)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_action_log_change_updates_hash(self):
        ctx = _ctx(workflow={'current_stage': '', 'allowed_actions': []})
        fp_a = fingerprint_digest(
            build_content_fingerprint(ctx, latest_action_log_id='log-a')
        )
        fp_b = fingerprint_digest(
            build_content_fingerprint(ctx, latest_action_log_id='log-b')
        )
        self.assertNotEqual(fp_a, fp_b)

    def test_workflow_version_changes_with_next_action(self):
        ctx = _ctx(
            workflow={
                'current_stage': 'Pickup',
                'next_action': {'action_code': 'A1'},
                'allowed_actions': [],
            },
            reconciliation={'reconciliation_version': 'r1'},
        )
        v1 = build_workflow_version(ctx)
        ctx.workflow = {
            'current_stage': 'Pickup',
            'next_action': {'action_code': 'A2'},
            'allowed_actions': [],
        }
        v2 = build_workflow_version(ctx)
        self.assertNotEqual(v1, v2)

    def test_entity_versions_include_booking_for_shipment(self):
        booking = MagicMock()
        booking.pk = uuid4()
        booking.booking_status = 'Active'
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = 'Loaded'
        ctx = _ctx(
            booking=booking,
            shipment=shipment,
            round_trip={'booking_execution_stage': 'PARTIAL'},
            reconciliation={'workflow_integrity': {}},
        )
        versions = build_entity_versions(ctx)
        self.assertTrue(versions['booking'])
        self.assertTrue(versions['shipment'])

    def test_build_sync_metadata_without_finalize(self):
        ctx = _ctx(
            workflow={'current_stage': '', 'allowed_actions': []},
            content_hash='preset',
        )
        meta = build_job_detail_sync_metadata(ctx)
        self.assertEqual(meta['content_hash'], 'preset')
