"""
Job Detail support menu — routes to standalone evidence capture (not job/empty flow).

Support shortcuts (Report Delay, Report Issue, Dispatch Support) and tenant
``without``-scope Operation Actions share the same ``evidence_capture`` screen.
"""
from __future__ import annotations

from typing import Any

from django_tenants.utils import schema_context

from mobile_api.execution.evidence.evidence_capture_ui import ISSUE_REPORT_SUBMIT_ENDPOINT
from mobile_api.helpers.action_navigation_metadata import (
    apply_standalone_evidence_capture_navigation_to_action_row,
    row_is_without_scope_action,
)
from mobile_api.helpers.action_execution_metadata import (
    project_allowed_action_row,
)
from mobile_api.helpers.i18n import get_localized_value
from tenant_workspace.models import TenantOperationAction

_SUPPORT_MENU_SPECS: tuple[dict[str, str], ...] = (
    {
        'menu_key': 'report_delay',
        'label_en': 'Report Delay',
        'label_ar': 'الإبلاغ عن تأخير',
        'issue_type': 'delay',
        'severity': 'medium',
        'notes_placeholder': (
            'Describe the delay reason, location, and expected recovery time.'
        ),
    },
    {
        'menu_key': 'report_issue',
        'label_en': 'Report Issue',
        'label_ar': 'الإبلاغ عن مشكلة',
        'issue_type': 'other',
        'severity': 'medium',
        'notes_placeholder': 'Describe the issue, location, and any relevant details.',
    },
    {
        'menu_key': 'request_dispatch_support',
        'label_en': 'Request Dispatch Support',
        'label_ar': 'طلب دعم من مركز التحكم',
        'issue_type': 'other',
        'severity': 'high',
        'notes_placeholder': 'Explain what dispatch support is needed.',
    },
)


def _iter_without_scope_actions(tenant_schema: str):
    schema = (tenant_schema or '').strip()
    if not schema:
        return
    try:
        with schema_context(schema):
            yield from (
                TenantOperationAction.objects.exclude(
                    status=TenantOperationAction.Status.INACTIVE,
                )
                .filter(action_scope__iexact='without')
                .order_by('sequence_number', 'action_code')
            )
    except Exception as exc:
        from django.test.testcases import DatabaseOperationForbidden

        if isinstance(exc, DatabaseOperationForbidden):
            return
        raise


def _issue_report_submit_contract(
    *,
    issue_type: str,
    severity: str,
    job_type: str = 'shipment',
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'issue_type': issue_type,
        'severity': severity,
        'notes': '{note}',
        'media': '{evidence_media}',
        'latitude': '{latitude}',
        'longitude': '{longitude}',
        'client_issue_id': '{client_issue_id}',
    }
    if (job_type or 'shipment').strip() == 'movement':
        payload['movement_id'] = '{job_id}'
    else:
        payload['shipment_id'] = '{job_id}'
    return {
        'type': 'issue_report',
        'endpoint': ISSUE_REPORT_SUBMIT_ENDPOINT,
        'method': 'POST',
        'payload': payload,
    }


def _localized_label(request: Any | None, *, english: str, arabic: str) -> str:
    if request is not None:
        return get_localized_value(request, english, arabic) or english
    return english


def build_support_menu_action_row(
    spec: dict[str, str],
    *,
    request: Any | None = None,
    job_type: str = 'shipment',
) -> dict[str, Any]:
    label = _localized_label(
        request,
        english=spec['label_en'],
        arabic=spec.get('label_ar', spec['label_en']),
    )
    row = {
        'menu_key': spec['menu_key'],
        'action_code': spec['menu_key'].upper(),
        'action_name': label,
        'execution_label': label,
        'label': label,
        'action_category': 'support',
        'screen_title': label,
        'execution_requirements': {
            'gps': True,
            'photo_enabled': True,
            'video_enabled': True,
            'photo_min_count': 0,
            'video_min_count': 0,
            'note': True,
            'note_required': False,
            'capture_mode': 'standalone_evidence',
            'requires_evidence_capture': True,
            'allow_submit_without_media': True,
            'notes_placeholder': spec.get('notes_placeholder', ''),
        },
    }
    return apply_standalone_evidence_capture_navigation_to_action_row(
        row,
        submit_contract=_issue_report_submit_contract(
            issue_type=spec['issue_type'],
            severity=spec['severity'],
            job_type=job_type,
        ),
        submit_button_label='Submit Report',
    )


def build_without_scope_action_row(
    action: Any,
    *,
    request: Any | None = None,
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Project one tenant ``without``-scope action for the support / overflow menu."""
    return project_allowed_action_row(
        action,
        request=request,
        shipment=shipment,
        tenant_schema=tenant_schema,
    )


def build_job_support_actions(
    *,
    request: Any | None = None,
    tenant_schema: str = '',
    shipment: Any | None = None,
    movement: Any | None = None,
) -> list[dict[str, Any]]:
    """
    Support modal actions for Job Detail.

    Always includes the three operational shortcuts; appends tenant-configured
    ``without``-scope Operation Actions (e.g. Incident Report, Cancel Movement).
    """
    if shipment is None and movement is None:
        return []

    job_type = 'movement' if movement is not None else 'shipment'
    actions: list[dict[str, Any]] = [
        build_support_menu_action_row(spec, request=request, job_type=job_type)
        for spec in _SUPPORT_MENU_SPECS
    ]

    seen_labels = {
        str(row.get('execution_label') or row.get('label') or '').strip().casefold()
        for row in actions
    }
    for action in _iter_without_scope_actions(tenant_schema):
        label = (
            (getattr(action, 'english_label', None) or '').strip()
            or str(getattr(action, 'action_code', '') or '').strip()
        )
        if label.casefold() in seen_labels:
            continue
        if not bool(getattr(action, 'mobile_visible', False)):
            continue
        row = build_without_scope_action_row(
            action,
            request=request,
            shipment=shipment,
            tenant_schema=tenant_schema,
        )
        actions.append(row)
        seen_labels.add(label.casefold())

    return actions


def is_support_navigation_row(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    if str(row.get('ui_mode') or '') == 'standalone_evidence':
        return True
    if row.get('linked_job_flow') is False:
        return True
    if row_is_without_scope_action(row):
        return True
    menu_key = str(row.get('menu_key') or '').strip()
    return bool(menu_key)
