"""
Sync empty-move workflow_status completion onto workflow.timeline_preview.

Mobile clients may render the stepper from ``workflow.timeline_preview`` while
completion is derived in ``workflow.workflow_status``. This module keeps both
in agreement after arrival / complete actions.
"""
from __future__ import annotations

from typing import Any

from mobile_api.job_detail.timeline.timeline_event_mapper import sort_timeline_display_order


def sync_workflow_status_to_timeline_preview(
    workflow_status: list[dict[str, Any]],
    timeline_preview: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Propagate performed flags from movement workflow_status onto timeline rows."""
    if not workflow_status or not timeline_preview:
        return list(timeline_preview or [])

    by_code: dict[str, dict[str, Any]] = {}
    by_step_key: dict[str, dict[str, Any]] = {}
    for step in workflow_status:
        code = str(step.get('action_code') or '').strip().casefold()
        if code:
            by_code[code] = step
        step_key = str(step.get('step_key') or '').strip()
        if step_key:
            by_step_key[step_key] = step

    synced: list[dict[str, Any]] = []
    for row in timeline_preview:
        out = dict(row)
        code = str(out.get('action_code') or '').strip().casefold()
        step = by_code.get(code)
        if step is None:
            step = by_step_key.get(str(out.get('step_key') or '').strip())
        if step is None or not (
            step.get('completed') or step.get('is_performed')
        ):
            synced.append(out)
            continue
        out['is_performed'] = True
        out['completed'] = True
        out['timeline_state'] = 'performed'
        if not out.get('step_key') and step.get('step_key'):
            out['step_key'] = step['step_key']
        if not out.get('display_timestamp') and step.get('display_timestamp'):
            out['display_timestamp'] = step['display_timestamp']
        if not out.get('timestamp') and step.get('timestamp'):
            out['timestamp'] = step['timestamp']
        if not out.get('action_id') and step.get('action_id'):
            out['action_id'] = step['action_id']
        synced.append(out)
    return synced


def attach_timeline_preview_to_workflow(
    workflow: dict[str, Any],
    timeline: dict[str, Any],
    *,
    job_type: str = '',
) -> dict[str, Any]:
    """
    Mirror timeline steps on workflow (booking / shipment / movement).

    For movement jobs, completion flags are synced from ``workflow_status``.
    """
    preview = list(timeline.get('timeline_preview') or [])
    if not preview:
        return dict(workflow or {})
    out = dict(workflow or {})
    preview = sort_timeline_display_order(preview)
    if (job_type or '').strip() == 'movement':
        preview = sync_workflow_status_to_timeline_preview(
            list(out.get('workflow_status') or []),
            preview,
        )
    out['timeline_preview'] = preview
    out['timeline_step_count'] = len(preview)
    return out
