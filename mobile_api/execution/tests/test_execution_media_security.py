"""
Media security policy tests.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.evidence.execution_media_security import ExecutionMediaSecurityService
from mobile_api.execution.exceptions import ExecuteActionError


class ExecutionMediaSecurityTests(SimpleTestCase):
    def _context(self, **payload):
        return ExecuteActionContext(
            driver=SimpleNamespace(pk='drv-1', driver_id='drv-1'),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='shipment',
            job_id='s1',
            action_code='A2',
            payload=payload,
        )

    def test_rejects_path_traversal(self):
        ctx = self._context(
            media=[{'media_type': 'photo', 'file_ref': '../etc/passwd'}],
        )
        with self.assertRaises(ExecuteActionError) as exc:
            ExecutionMediaSecurityService().validate_media(ctx)
        self.assertEqual(exc.exception.code, 'media_path_traversal')

    def test_rejects_unknown_prefix(self):
        ctx = self._context(
            media=[{'media_type': 'photo', 'file_ref': 'evil/bad.jpg'}],
        )
        with self.assertRaises(ExecuteActionError) as exc:
            ExecutionMediaSecurityService().validate_media(ctx)
        self.assertEqual(exc.exception.code, 'media_path_not_allowed')

    @patch('mobile_api.execution.evidence.execution_media_security.mobile_execution_verify_media_storage', return_value=False)
    def test_accepts_valid_prefix_without_storage_check(self, _mock_verify):
        ctx = self._context(
            media=[
                {
                    'media_type': 'photo',
                    'file_ref': 'tenant_operation_action_media/OAM_abc123.jpg',
                },
            ],
        )
        items = ExecutionMediaSecurityService().validate_media(ctx)
        self.assertEqual(len(items), 1)

    @patch('mobile_api.execution.evidence.execution_media_security.mobile_execution_verify_media_storage', return_value=False)
    def test_accepts_multipart_execute_upload_path(self, _mock_verify):
        ctx = self._context(
            media=[
                {
                    'media_type': 'photo',
                    'file_ref': 'mobile/evidence/a1b2c3d4e5f6.jpg',
                },
            ],
        )
        items = ExecutionMediaSecurityService().validate_media(ctx)
        self.assertEqual(len(items), 1)

    @patch('django.core.files.storage.default_storage')
    @patch('mobile_api.execution.evidence.execution_media_security.mobile_execution_verify_media_storage', return_value=True)
    def test_requires_storage_exists_when_enabled(self, _mock_flag, mock_storage):
        mock_storage.exists.return_value = False
        ctx = self._context(
            media=[
                {
                    'media_type': 'photo',
                    'file_ref': 'tenant_operation_action_media/OAM_abc123.jpg',
                },
            ],
        )
        with self.assertRaises(ExecuteActionError) as exc:
            ExecutionMediaSecurityService().validate_media(ctx)
        self.assertEqual(exc.exception.code, 'media_storage_not_found')
