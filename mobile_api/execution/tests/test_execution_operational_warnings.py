"""
Execution advisory overlays for unresolved operational issues.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mobile_api.tests.transaction_test_case import TransactionTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.evidence.evidence_validation_service import (
    EvidenceValidationService,
)
from mobile_api.execution.services.execution_validation_service import (
    ExecutionValidationService,
)
from mobile_api.issues.models.operational_issue import OperationalIssue


class ExecutionOperationalWarningsTests(TransactionTestCase):
    def test_execution_warning_overlay_does_not_raise(self):
        shipment_id = str(uuid.uuid4())
        OperationalIssue.objects.create(
            tenant_schema='tenant_exec',
            shipment_id=shipment_id,
            driver_id='drv-1',
            client_issue_id=f'issue-{uuid.uuid4()}',
            issue_type='route_blocked',
            severity='critical',
            notes='Road closed',
            escalation_state=OperationalIssue.EscalationState.ESCALATED,
            blocking_recommended=True,
        )

        ctx = ExecuteActionContext(
            driver=SimpleNamespace(pk='drv-1'),
            tenant_schema='tenant_exec',
            user_id='u1',
            job_type='shipment',
            job_id=shipment_id,
            action_code='A2',
            shipment=SimpleNamespace(pk=shipment_id, shipment_id=shipment_id),
            operation_action=MagicMock(action_code='A2'),
            payload={'notes': 'proceed anyway'},
        )

        with patch(
            'mobile_api.execution.evidence.evidence_validation_service.build_execution_requirements',
            return_value={'gps': False, 'photo': False, 'photo_min_count': 0, 'video': False, 'video_min_count': 0, 'note': False, 'signature': False},
        ), patch.object(
            EvidenceValidationService()._media_security,
            'validate_media',
            lambda _ctx: None,
        ):
            EvidenceValidationService().validate_required_evidence(ctx)

        self.assertGreaterEqual(ctx.alerts.get('unresolved_issue_count', 0), 1)
        self.assertFalse((ctx.alerts.get('execution_warning_overlay') or {}).get('hard_block'))

    def test_execution_validation_service_warning_overlay(self):
        shipment_id = str(uuid.uuid4())
        OperationalIssue.objects.create(
            tenant_schema='tenant_exec',
            shipment_id=shipment_id,
            driver_id='drv-1',
            client_issue_id=f'issue-{uuid.uuid4()}',
            issue_type='delay',
            severity='medium',
            notes='Late',
            escalation_state=OperationalIssue.EscalationState.OPEN,
            blocking_recommended=False,
        )
        ctx = ExecuteActionContext(
            driver=SimpleNamespace(pk='drv-1'),
            tenant_schema='tenant_exec',
            user_id='u1',
            job_type='shipment',
            job_id=shipment_id,
            action_code='A2',
            shipment=SimpleNamespace(pk=shipment_id, shipment_id=shipment_id),
        )
        ExecutionValidationService._attach_operational_issue_warnings(ctx)
        overlay = ctx.resolver_meta.get('operational_issue_warnings', {}).get(
            'execution_warning_overlay',
            {},
        )
        self.assertTrue(overlay.get('has_warnings'))
        self.assertFalse(overlay.get('hard_block'))
