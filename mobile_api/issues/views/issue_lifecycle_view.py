"""
mobile_api/issues/views/issue_lifecycle_view.py

Supervisor issue lifecycle endpoints.
"""
from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from mobile_api.issues.models.operational_issue import OperationalIssue
from mobile_api.issues.serializers.issue_lifecycle_serializer import (
    IssueLifecycleRequestSerializer,
)
from mobile_api.issues.services.issue_escalation_service import IssueEscalationService
from mobile_api.job_detail.services.job_detail_driver_resolver import tenant_schema_for_request
from mobile_api.permissions import HasViewMobileCapability, IsMobileAuthenticated
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.issues.lifecycle')


class IssueLifecycleAPIView(MobileAPIView):
    """Supervisor-only lifecycle transition endpoint."""

    permission_classes = [IsMobileAuthenticated, HasViewMobileCapability]
    required_mobile_capability = 'mobile.operations.write'
    throttle_classes = [MobileUserThrottle]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = IssueEscalationService()

    def post(self, request, issue_id: str, operation: str):
        serializer = IssueLifecycleRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        tenant_schema = tenant_schema_for_request(request)
        if not tenant_schema:
            return self.error(
                message=_('mobile.auth.tenant_required'),
                code='tenant_required',
                message_key='mobile.auth.tenant_required',
                http_code=400,
            )

        issue = get_object_or_404(
            OperationalIssue,
            pk=issue_id,
            tenant_schema=(tenant_schema or '').strip(),
        )

        notes = str(serializer.validated_data.get('notes') or '').strip()
        operation_code = (operation or '').strip().casefold()

        if operation_code == 'acknowledge':
            event = self._service.acknowledge(issue, notes=notes)
        elif operation_code == 'resolve':
            event = self._service.resolve(issue, notes=notes)
        elif operation_code == 'reject':
            event = self._service.reject(issue, notes=notes)
        elif operation_code == 'reopen':
            event = self._service.reopen(issue, notes=notes)
        else:
            return self.error(
                message=_('mobile.validation.failed'),
                code='invalid_issue_operation',
                message_key='mobile.validation.failed',
                http_code=400,
            )

        payload = {
            'issue': {
                'issue_id': str(issue.pk),
                'client_issue_id': issue.client_issue_id,
                'escalation_state': issue.escalation_state,
                'resolved_at': issue.resolved_at.isoformat() if issue.resolved_at else None,
            },
            'lifecycle_event': {
                'event_id': str(event.pk),
                'event_type': event.event_type,
                'from_state': event.from_state,
                'to_state': event.to_state,
                'recorded_at': event.recorded_at.isoformat() if event.recorded_at else None,
            },
            'timeline_preview': self._service.build_timeline_preview(issue),
            'authority': self._service.build_issue_authority(issue),
        }

        logger.info(
            'issue_lifecycle tenant=%s issue=%s operation=%s state=%s',
            tenant_schema,
            issue_id,
            operation_code,
            issue.escalation_state,
        )

        return self.success(
            message=_('mobile.success.data_retrieved'),
            data=payload,
            message_key='mobile.success.data_retrieved',
            http_code=200,
        )
