"""
mobile_api/issues/dto/issue_response_builder.py
"""
from __future__ import annotations

from typing import Any


class IssueResponseBuilder:
    def build_response(
        self,
        *,
        issue: Any,
        evidence_rows: list[Any],
        escalation: dict[str, Any],
        timeline_preview: dict[str, Any],
        workflow_impact: dict[str, Any],
        replayed: bool,
    ) -> dict[str, Any]:
        media = [
            {
                'media_type': getattr(r, 'media_type', '') or '',
                'file_ref': getattr(r, 'file_ref', '') or '',
                'file_name': getattr(r, 'file_name', '') or '',
                'immutable': bool(getattr(r, 'immutable', True)),
            }
            for r in evidence_rows
        ]

        issue_payload = {
            'issue_id': str(getattr(issue, 'pk', '') or getattr(issue, 'id', '')),
            'client_issue_id': (getattr(issue, 'client_issue_id', None) or '').strip(),
            'shipment_id': (getattr(issue, 'shipment_id', None) or '').strip(),
            'driver_id': (getattr(issue, 'driver_id', None) or '').strip(),
            'issue_type': (getattr(issue, 'issue_type', None) or '').strip(),
            'severity': (getattr(issue, 'severity', None) or '').strip(),
            'notes': (getattr(issue, 'notes', None) or '').strip(),
            'escalation_state': (getattr(issue, 'escalation_state', None) or '').strip(),
            'blocking_recommended': bool(getattr(issue, 'blocking_recommended', False)),
            'created_at': (
                issue.created_at.isoformat()
                if getattr(issue, 'created_at', None)
                else None
            ),
            'resolved_at': (
                issue.resolved_at.isoformat()
                if getattr(issue, 'resolved_at', None)
                else None
            ),
            'media_count': len(media),
            'media': media,
            'replayed': bool(replayed),
        }

        return {
            'issue': issue_payload,
            'escalation': dict(escalation or {}),
            'timeline_preview': dict(timeline_preview or {}),
            'workflow_impact': {
                'blocking_recommended': bool(
                    workflow_impact.get('blocking_recommended', False)
                ),
                'unresolved_issue_count': int(
                    workflow_impact.get('unresolved_issue_count') or 0
                ),
                'has_unresolved_issues': bool(
                    workflow_impact.get('has_unresolved_issues', False)
                ),
                'workflow_mutation_performed': False,
                'execute_action_required_for_progression': bool(
                    workflow_impact.get('execute_action_required_for_progression', False)
                ),
            },
            'next_step': {
                'requires_execute_action': bool(
                    workflow_impact.get('execute_action_required_for_progression', False)
                ),
            },
        }
