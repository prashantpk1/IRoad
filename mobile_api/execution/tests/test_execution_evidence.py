"""
Evidence validation and media persistence tests.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.evidence.action_log_media_persistence import (
    ActionLogMediaItem,
    persist_action_log_media_rows,
)
from mobile_api.execution.evidence.constants import EXECUTION_MEDIA_MAX_ITEMS
from mobile_api.execution.evidence.action_log_media_persistence import normalize_media_items
from mobile_api.execution.evidence.evidence_validation_service import EvidenceValidationService
from mobile_api.execution.evidence.execution_media_security import ExecutionMediaSecurityService
from mobile_api.execution.evidence.execution_media_service import ExecutionMediaService
from mobile_api.execution.exceptions import ExecuteActionError


def _action(**overrides):
    base = dict(
        action_code='A1',
        english_label='Start Job',
        arabic_label='',
        action_scope='',
        sequence_category='',
        sequence_number=1,
        movement_status_impact='Started',
        shipment_status_impact='',
        booking_status_impact='',
        auto_pod_post=False,
        auto_movement_post=False,
        auto_shipment_post=False,
        hard_copy_collection=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _context(**kwargs):
    defaults = dict(
        driver=SimpleNamespace(pk='d1'),
        tenant_schema='tenant_test',
        user_id='u1',
        job_type='shipment',
        job_id='ship-1',
        action_code='A1',
        operation_action=_action(),
        payload={},
    )
    defaults.update(kwargs)
    return ExecuteActionContext(**defaults)


class EvidenceValidationTests(SimpleTestCase):
    def setUp(self):
        self._media_security_patch = patch.object(
            ExecutionMediaSecurityService,
            'validate_media',
            side_effect=lambda ctx: normalize_media_items(
                list((ctx.payload or {}).get('media') or []),
            ),
        )
        self._media_security_patch.start()

    def tearDown(self):
        self._media_security_patch.stop()

    def test_missing_gps_raises(self):
        ctx = _context(payload={'latitude': '', 'longitude': ''})
        with self.assertRaises(ExecuteActionError) as exc:
            EvidenceValidationService().validate_required_evidence(ctx)
        self.assertEqual(exc.exception.code, 'gps_required')

    def test_gps_passes_when_provided(self):
        ctx = _context(
            payload={'latitude': '25.0', 'longitude': '55.0'},
        )
        EvidenceValidationService().validate_required_evidence(ctx)

    def test_missing_notes_raises(self):
        ctx = _context(
            operation_action=_action(
                action_code='A9',
                english_label='Collect Payment',
                movement_status_impact='',
            ),
            payload={'notes': ''},
        )
        with self.assertRaises(ExecuteActionError) as exc:
            EvidenceValidationService().validate_required_evidence(ctx)
        self.assertEqual(exc.exception.code, 'notes_required')

    def test_invalid_media_type(self):
        ctx = _context(
            payload={
                'latitude': '1',
                'longitude': '2',
                'media': [{'media_type': 'audio', 'file_ref': 'x'}],
            },
        )
        with patch(
            'mobile_api.execution.evidence.evidence_validation_service.build_execution_requirements',
            return_value={
                'gps': True,
                'photo': True,
                'photo_min_count': 1,
                'video': False,
                'video_min_count': 0,
                'note': False,
                'signature': False,
            },
        ):
            with self.assertRaises(ExecuteActionError) as exc:
                EvidenceValidationService().validate_required_evidence(ctx)
        self.assertEqual(exc.exception.code, 'invalid_media_type')

    def test_upload_limit_exceeded(self):
        media = [
            {
                'media_type': 'photo',
                'file_ref': f'tenant_operation_action_media/OAM_{i}.jpg',
            }
            for i in range(EXECUTION_MEDIA_MAX_ITEMS + 1)
        ]
        ctx = _context(payload={'media': media})
        with patch(
            'mobile_api.execution.evidence.evidence_validation_service.build_execution_requirements',
            return_value={
                'gps': False,
                'photo': True,
                'photo_min_count': 1,
                'video': False,
                'video_min_count': 0,
                'note': False,
                'signature': False,
            },
        ):
            with self.assertRaises(ExecuteActionError) as exc:
                EvidenceValidationService().validate_required_evidence(ctx)
        self.assertEqual(exc.exception.code, 'media_limit_exceeded')

    def test_photo_required_count(self):
        ctx = _context(
            payload={
                'media': [
                    {
                        'media_type': 'document',
                        'file_ref': 'tenant_operation_action_media/OAM_doc1.pdf',
                    },
                ],
            },
        )
        with patch(
            'mobile_api.execution.evidence.evidence_validation_service.build_execution_requirements',
            return_value={
                'gps': False,
                'photo': True,
                'photo_min_count': 1,
                'video': False,
                'video_min_count': 0,
                'note': False,
                'signature': False,
            },
        ):
            with self.assertRaises(ExecuteActionError) as exc:
                EvidenceValidationService().validate_required_evidence(ctx)
        self.assertEqual(exc.exception.code, 'photo_required')

    def test_signature_required(self):
        ctx = _context(
            payload={
                'media': [
                    {
                        'media_type': 'photo',
                        'file_ref': 'tenant_operation_action_media/OAM_p1.jpg',
                    },
                ],
            },
        )
        with patch(
            'mobile_api.execution.evidence.evidence_validation_service.build_execution_requirements',
            return_value={
                'gps': False,
                'photo': True,
                'photo_min_count': 1,
                'video': False,
                'video_min_count': 0,
                'note': False,
                'signature': True,
            },
        ):
            with self.assertRaises(ExecuteActionError) as exc:
                EvidenceValidationService().validate_required_evidence(ctx)
        self.assertEqual(exc.exception.code, 'signature_required')

    def test_idempotent_replay_skips_evidence(self):
        ctx = _context(payload={}, idempotent_replay=True)
        EvidenceValidationService().validate_required_evidence(ctx)


class ExecutionMediaPersistenceTests(SimpleTestCase):
    def test_successful_persistence_calls_create(self):
        action_log = MagicMock()
        action_log.media_rows.filter.return_value.first.return_value = None
        media_obj = MagicMock(pk='media-1')
        created: list = []

        def _create(**kwargs):
            obj = MagicMock(pk=f'media-{len(created)}')
            created.append(obj)
            return obj

        with patch(
            'mobile_api.execution.evidence.action_log_media_persistence.TenantOperationActionMedia',
        ) as mock_model:
            mock_model.side_effect = lambda **kw: _create(**kw)
            mock_model.objects = MagicMock()
            items = [
                ActionLogMediaItem(media_type='photo', file_ref='path/a.jpg', line_no=1),
                ActionLogMediaItem(media_type='video', file_ref='path/b.mp4', line_no=2),
            ]
            ids = persist_action_log_media_rows(action_log, items)
        self.assertEqual(len(ids), 2)
        action_log.media_rows.exclude.assert_called_once()

    def test_persist_execution_media_skips_replay(self):
        ctx = _context(
            idempotent_replay=True,
            action_log=MagicMock(),
            payload={'media': [{'media_type': 'photo', 'file_ref': 'x'}]},
        )
        result = ExecutionMediaService().persist_execution_media(ctx)
        self.assertEqual(result, [])

    def test_persist_execution_media_delegates(self):
        ctx = _context(
            action_log=MagicMock(),
            payload={
                'media': [
                    {
                        'media_type': 'photo',
                        'file_ref': 'tenant_operation_action_media/OAM_abc.jpg',
                        'sort_order': 1,
                    },
                ],
            },
        )
        with patch(
            'mobile_api.execution.evidence.execution_media_service.persist_action_log_media_rows',
            return_value=['id-1'],
        ) as mock_persist:
            ids = ExecutionMediaService().persist_execution_media(ctx)
        self.assertEqual(ids, ['id-1'])
        mock_persist.assert_called_once()
        self.assertIn('media_row_ids', ctx.resolver_meta)

    def test_rollback_safety_propagates_failure_before_replace(self):
        """
        Persistence must not swallow errors — orchestrator atomic rolls back execute.

        When the second ``save()`` fails, the exception propagates (no delete/replace).
        """
        action_log = MagicMock()
        action_log.media_rows.filter.return_value.first.return_value = None
        call_count = {'n': 0}

        def _save_side_effect():
            call_count['n'] += 1
            if call_count['n'] == 2:
                raise RuntimeError('simulated DB failure')

        with patch(
            'mobile_api.execution.evidence.action_log_media_persistence.TenantOperationActionMedia',
        ) as mock_model:
            def _factory(**kwargs):
                obj = MagicMock()
                obj.pk = f'pk-{call_count["n"]}'
                obj.save.side_effect = _save_side_effect
                return obj

            mock_model.side_effect = _factory
            items = [
                ActionLogMediaItem(media_type='photo', file_ref='a', line_no=1),
                ActionLogMediaItem(media_type='photo', file_ref='b', line_no=2),
            ]
            with self.assertRaises(RuntimeError):
                persist_action_log_media_rows(action_log, items)

        self.assertEqual(call_count['n'], 2)
        action_log.media_rows.exclude.assert_not_called()
