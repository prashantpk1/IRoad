"""
mobile_api/job_detail/projections/job_detail_projection_builder.py

Operational issue visibility for Job Detail and execution warning overlays.

Read-only projections — does not mutate workflow or shipment_status.
"""
from __future__ import annotations

from typing import Any

from mobile_api.issues.models.operational_issue import (
    OperationalIssue,
    OperationalIssueEscalationEvent,
)
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.services.operational_reconciliation_service import (
    OperationalReconciliationService,
)
from mobile_api.job_detail.timeline.timeline_event_mapper import (
    map_escalation_events_to_timeline,
    merge_issue_events_into_timeline,
)


def _shipment_pk(context: JobDetailContext) -> str:
    shipment = context.shipment
    if shipment is not None:
        return str(
            getattr(shipment, 'pk', None)
            or getattr(shipment, 'shipment_id', None)
            or context.job_id
            or ''
        ).strip()
    return str(context.job_id or '').strip()


def _job_scope_id(context: JobDetailContext) -> str:
    if context.job_type == 'movement' and context.movement is not None:
        return str(
            getattr(context.movement, 'pk', None)
            or getattr(context.movement, 'movement_id', None)
            or context.job_id
            or ''
        ).strip()
    return _shipment_pk(context)


def load_operational_issues(
    *,
    tenant_schema: str,
    shipment_id: str,
) -> list[OperationalIssue]:
    if not (tenant_schema and shipment_id):
        return []
    return list(
        OperationalIssue.objects.filter(
            tenant_schema=(tenant_schema or '').strip(),
            shipment_id=(shipment_id or '').strip(),
        ).order_by('-created_at')
    )


def build_operational_issue_row(issue: OperationalIssue) -> dict[str, Any]:
    return {
        'issue_id': str(issue.pk),
        'client_issue_id': (issue.client_issue_id or '').strip(),
        'shipment_id': (issue.shipment_id or '').strip(),
        'driver_id': (issue.driver_id or '').strip(),
        'issue_type': (issue.issue_type or '').strip(),
        'severity': (issue.severity or '').strip(),
        'notes': (issue.notes or '').strip(),
        'escalation_state': (issue.escalation_state or '').strip(),
        'blocking_recommended': bool(issue.blocking_recommended),
        'created_at': issue.created_at.isoformat() if issue.created_at else None,
        'resolved_at': issue.resolved_at.isoformat() if issue.resolved_at else None,
        'unresolved': issue.is_unresolved,
    }


def build_operational_issues_visibility(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Job Detail contract::

        operational_issues: list
        unresolved_issue_count: int
        blocking_recommendation: bool
    """
    _ = request
    if context.job_type not in {'shipment', 'movement'}:
        return {
            'operational_issues': [],
            'unresolved_issue_count': 0,
            'blocking_recommendation': False,
        }
    if context.job_type == 'shipment' and context.shipment is None:
        return {
            'operational_issues': [],
            'unresolved_issue_count': 0,
            'blocking_recommendation': False,
        }
    if context.job_type == 'movement' and context.movement is None:
        return {
            'operational_issues': [],
            'unresolved_issue_count': 0,
            'blocking_recommendation': False,
        }

    tenant_schema = (context.tenant_schema or '').strip()
    scope_id = _job_scope_id(context)
    issues = load_operational_issues(
        tenant_schema=tenant_schema,
        shipment_id=scope_id,
    )

    unresolved = [row for row in issues if row.is_unresolved]
    blocking_recommendation = any(bool(row.blocking_recommended) for row in unresolved)

    return {
        'operational_issues': [build_operational_issue_row(row) for row in issues],
        'unresolved_issue_count': len(unresolved),
        'blocking_recommendation': blocking_recommendation,
    }


def build_escalation_alerts(
    issues: list[OperationalIssue],
) -> list[dict[str, Any]]:
    """Supervisor-facing escalation alerts (advisory only)."""
    alerts: list[dict[str, Any]] = []
    for issue in issues:
        if not issue.is_unresolved:
            continue
        state = (issue.escalation_state or '').strip()
        if state not in {
            OperationalIssue.EscalationState.ESCALATED,
            OperationalIssue.EscalationState.OPEN,
        }:
            continue
        alerts.append(
            {
                'issue_id': str(issue.pk),
                'issue_type': issue.issue_type,
                'severity': issue.severity,
                'escalation_state': state,
                'blocking_recommended': bool(issue.blocking_recommended),
                'message_key': 'mobile.issues.escalation_alert',
            }
        )
    return alerts


def build_issue_timeline_events(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> list[dict[str, Any]]:
    """Load escalation milestones for timeline merge (opened / escalated / resolved)."""
    if context.job_type != 'shipment' or context.shipment is None:
        return []

    tenant_schema = (context.tenant_schema or '').strip()
    shipment_id = _shipment_pk(context)
    issues = load_operational_issues(
        tenant_schema=tenant_schema,
        shipment_id=shipment_id,
    )
    if not issues:
        return []

    issue_ids = [issue.pk for issue in issues]
    events = list(
        OperationalIssueEscalationEvent.objects.filter(
            issue_id__in=issue_ids,
        ).select_related('issue').order_by('-recorded_at')
    )
    by_issue = {str(issue.pk): issue for issue in issues}
    return map_escalation_events_to_timeline(
        events,
        issues_by_id=by_issue,
        request=request,
    )


def enrich_timeline_with_operational_issues(
    timeline_bundle: dict[str, Any],
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Merge issue timeline milestones into Action Log timeline preview.

    Not used by Job Detail main timeline (issues stay in alerts only).
    Kept for reconciliation/unit tests and optional future overlays.
    """
    bundle = dict(timeline_bundle or {})
    if context.job_type != 'shipment' or context.shipment is None:
        return bundle

    overlay_events = OperationalReconciliationService().build_timeline_overlays(
        context=context,
        request=request,
    )
    if not overlay_events:
        return bundle

    merged = merge_issue_events_into_timeline(
        list(bundle.get('timeline_preview') or []),
        overlay_events,
    )
    bundle['timeline_preview'] = merged
    bundle['includes_operational_issues'] = True
    return bundle


def apply_operational_issues_visibility(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> JobDetailContext:
    """
    Attach operational issue visibility to context and enrich timeline preview.

    Called after base timeline projection is built.
    """
    visibility = build_operational_issues_visibility(context, request=request)
    context.resolver_meta = dict(context.resolver_meta or {})
    context.resolver_meta['operational_issues_visibility'] = visibility
    context.resolver_meta['operational_reconciliation'] = OperationalReconciliationService().reconcile(
        context=context,
        request=request,
    )

    alerts = dict(context.alerts or {})
    if visibility.get('unresolved_issue_count'):
        alerts['has_operational_issues'] = True
    existing_escalation_alerts = list(alerts.get('escalation_alerts') or [])
    new_escalation_alerts = build_escalation_alerts(
        load_operational_issues(
            tenant_schema=(context.tenant_schema or '').strip(),
            shipment_id=_shipment_pk(context),
        )
    )
    merged_alerts: list[dict[str, Any]] = []
    seen_issue_ids: set[str] = set()
    for alert in existing_escalation_alerts + new_escalation_alerts:
        issue_id = str(alert.get('issue_id') or '').strip()
        if issue_id and issue_id in seen_issue_ids:
            continue
        if issue_id:
            seen_issue_ids.add(issue_id)
        merged_alerts.append(alert)
    alerts['escalation_alerts'] = merged_alerts
    alerts['unresolved_issue_count'] = max(
        int(alerts.get('unresolved_issue_count') or 0),
        int(visibility.get('unresolved_issue_count') or 0),
    )
    if merged_alerts or alerts.get('unresolved_issue_count'):
        alerts['has_operational_issues'] = True
    context.alerts = alerts
    return context


def build_execution_operational_warnings(
    *,
    tenant_schema: str,
    job_type: str,
    shipment: Any | None,
    job_id: str,
    action_code: str = '',
) -> dict[str, Any]:
    """
    Advisory execution overlay — never blocks kernel execute.

    Used by execute validation layers to influence recommendations only (no hard-block).
    """
    if job_type != 'shipment' or shipment is None:
        return {
            'operational_issues': [],
            'unresolved_issue_count': 0,
            'blocking_recommendation': False,
            'escalation_alerts': [],
            'execution_warning_overlay': {
                'has_warnings': False,
                'hard_block': False,
                'warnings': [],
            },
        }

    shipment_id = str(
        getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', None) or job_id
    ).strip()
    issues = load_operational_issues(
        tenant_schema=(tenant_schema or '').strip(),
        shipment_id=shipment_id,
    )
    unresolved = [row for row in issues if row.is_unresolved]
    blocking_recommendation = any(bool(row.blocking_recommended) for row in unresolved)
    escalation_alerts = build_escalation_alerts(issues)

    warnings: list[dict[str, Any]] = []
    if unresolved:
        warnings.append(
            {
                'code': 'unresolved_operational_issues',
                'severity': 'warning',
                'message_key': 'mobile.issues.unresolved_warning',
                'count': len(unresolved),
            }
        )
    if blocking_recommendation:
        warnings.append(
            {
                'code': 'blocking_recommended',
                'severity': 'advisory',
                'message_key': 'mobile.issues.blocking_recommended_advisory',
                'hard_block': False,
            }
        )
    if escalation_alerts:
        warnings.append(
            {
                'code': 'escalation_alerts',
                'severity': 'info',
                'message_key': 'mobile.issues.escalation_alerts',
                'count': len(escalation_alerts),
            }
        )

    return {
        'operational_issues': [build_operational_issue_row(row) for row in unresolved],
        'unresolved_issue_count': len(unresolved),
        'blocking_recommendation': blocking_recommendation,
        'escalation_alerts': escalation_alerts,
        'execution_warning_overlay': {
            'has_warnings': bool(warnings),
            'hard_block': False,
            'warnings': warnings,
            'target_action_code': (action_code or '').strip(),
        },
    }


def attach_operational_issue_warnings_to_execute_context(context: Any) -> None:
    """
    Attach advisory operational issue warnings to execute context (no hard-block).

    Used by ``ExecutionValidationService`` and ``EvidenceValidationService``.
    """
    warnings = build_execution_operational_warnings(
        tenant_schema=(getattr(context, 'tenant_schema', None) or '').strip(),
        job_type=str(getattr(context, 'job_type', '') or ''),
        shipment=getattr(context, 'shipment', None),
        job_id=str(getattr(context, 'job_id', '') or ''),
        action_code=(getattr(context, 'action_code', None) or '').strip(),
    )

    resolver_meta = dict(getattr(context, 'resolver_meta', None) or {})
    resolver_meta['operational_issue_warnings'] = warnings
    context.resolver_meta = resolver_meta

    alerts = dict(getattr(context, 'alerts', None) or {})
    alerts['operational_issues'] = list(warnings.get('operational_issues') or [])
    alerts['unresolved_issue_count'] = max(
        int(alerts.get('unresolved_issue_count') or 0),
        int(warnings.get('unresolved_issue_count') or 0),
    )
    alerts['blocking_recommendation'] = bool(
        alerts.get('blocking_recommendation') or warnings.get('blocking_recommendation')
    )
    existing_escalation_alerts = list(alerts.get('escalation_alerts') or [])
    new_escalation_alerts = list(warnings.get('escalation_alerts') or [])
    merged_escalation_alerts: list[dict[str, Any]] = []
    seen_issue_ids: set[str] = set()
    for alert in existing_escalation_alerts + new_escalation_alerts:
        issue_id = str(alert.get('issue_id') or '').strip()
        if issue_id and issue_id in seen_issue_ids:
            continue
        if issue_id:
            seen_issue_ids.add(issue_id)
        merged_escalation_alerts.append(alert)
    alerts['escalation_alerts'] = merged_escalation_alerts
    overlay = dict(warnings.get('execution_warning_overlay') or {})
    if overlay.get('has_warnings'):
        alerts['execution_warning_overlay'] = overlay
    if alerts['unresolved_issue_count'] or merged_escalation_alerts:
        alerts['has_operational_issues'] = True
    context.alerts = alerts
