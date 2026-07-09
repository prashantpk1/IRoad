"""
Mobile execution metadata for Action Master rows.

IMPORTANT: Allowed-action *membership* is ONLY from ``get_allowed_actions()``.
This module projects UI/evidence metadata from configured action rows — it does
not filter or reorder the policy engine output.
"""

from __future__ import annotations

from typing import Any

from iroad_tenants.operation_execution import action_matches
from mobile_api.helpers.i18n import get_localized_value


def _is_hard_copy_action(action) -> bool:
    if action is None:
        return False
    return bool(getattr(action, 'hard_copy_collection', False))


def _localized_action_name(action, request=None) -> str:
    english = (getattr(action, 'english_label', None) or action.action_code or '').strip()
    arabic = (getattr(action, 'arabic_label', None) or '').strip()
    if request is not None:
        return get_localized_value(request, english, arabic) or action.action_code or ''
    return english or action.action_code or ''


def _tenant_evidence_flag(action, field_name: str) -> bool | None:
    """Explicit tenant Action Master flag when present (future portal toggles)."""
    if action is None or not hasattr(action, field_name):
        return None
    return bool(getattr(action, field_name, False))


def _tenant_evidence_min_count(action, field_name: str) -> int | None:
    if action is None or not hasattr(action, field_name):
        return None
    raw = getattr(action, field_name, None)
    if raw is None:
        return None
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return None


def _is_start_job_action(action) -> bool:
    if action is None:
        return False
    return action_matches(action, 'start job', 'action 1')


def infer_requires_gps(action) -> bool:
    if action is None or _is_hard_copy_action(action):
        return False
    from iroad_tenants.operation_runtime.movement_action_validator import (
        is_empty_move_catalog_action,
        is_without_scope_catalog_action,
    )
    from mobile_api.helpers.empty_move_action_resolver import (
        empty_move_route_endpoint_side,
    )

    if is_without_scope_catalog_action(action):
        return False
    if is_empty_move_catalog_action(action) and empty_move_route_endpoint_side(action):
        return True
    explicit = _tenant_evidence_flag(action, 'requires_gps')
    if explicit is not None:
        return explicit
    return True


def infer_show_photo_slot(action) -> bool:
    """Evidence UI may offer photo capture (not the same as mandatory)."""
    if action is None or _is_hard_copy_action(action):
        return False
    explicit = _tenant_evidence_flag(action, 'requires_photo')
    if explicit is False:
        return False
    return True


def infer_show_video_slot(action) -> bool:
    """Evidence UI may offer video capture (not the same as mandatory)."""
    if action is None or _is_hard_copy_action(action):
        return False
    explicit = _tenant_evidence_flag(action, 'requires_video')
    if explicit is False:
        return False
    return True


from mobile_api.helpers.evidence_requirement_flags import (
    normalize_evidence_requirements,
    sync_row_evidence_flags,
)


def infer_requires_note(action) -> bool:
    if action is None or _is_start_job_action(action):
        return False
    if bool(getattr(action, 'auto_treasury_post', False)):
        return True
    label = (getattr(action, 'english_label', None) or '').casefold()
    if 'collect payment' in label or 'cod' in label:
        return True
    return bool((getattr(action, 'booking_status_impact', None) or '').strip())


def build_execution_requirements(action, *, shipment=None) -> dict[str, Any]:
    """Structured capture requirements for mobile execute-action UI."""
    if _is_hard_copy_action(action):
        return {
            'gps': False,
            'photo': False,
            'photo_min_count': 0,
            'video': False,
            'video_min_count': 0,
            'video_max_count': 0,
            'video_optional': False,
            'note': False,
            'note_required': False,
            'signature': False,
            'auto_movement_post': bool(getattr(action, 'auto_movement_post', False)),
            'auto_pod_post': bool(getattr(action, 'auto_pod_post', False)),
            'auto_shipment_post': bool(getattr(action, 'auto_shipment_post', False)),
            'auto_treasury_post': bool(getattr(action, 'auto_treasury_post', False)),
            'hard_copy_collection': True,
            'custody_submission_required': True,
            'capture_mode': 'hard_copy_confirmation',
            'direct_execute': False,
            'requires_evidence_capture': False,
            'shipment_status_impact': (action.shipment_status_impact or '').strip()
            if action
            else '',
            'movement_status_impact': (action.movement_status_impact or '').strip()
            if action
            else '',
            'sequence_category': (getattr(action, 'sequence_category', None) or '').strip()
            if action
            else '',
        }

    photo_min = _tenant_evidence_min_count(action, 'photo_min_count')
    if photo_min is None:
        photo_min = 0
    video_min = _tenant_evidence_min_count(action, 'video_min_count')
    if video_min is None:
        video_min = 0
    video_max = int(getattr(action, 'video_max_count', None) or 0) if action else 0

    requires_gps = infer_requires_gps(action)
    show_photo = infer_show_photo_slot(action)
    show_video = infer_show_video_slot(action)

    from mobile_api.execution.evidence.constants import (
        POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
    )

    return normalize_evidence_requirements(
        {
            'gps': requires_gps,
            'photo_enabled': show_photo,
            'video_enabled': show_video,
            'photo_min_count': photo_min,
            'video_min_count': video_min,
            'video_max_count': video_max,
            'video_max_duration_seconds': POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
            'note': True,
            'note_required': False,
            'signature': bool(getattr(action, 'requires_signature', False)) if action else False,
            'auto_movement_post': bool(getattr(action, 'auto_movement_post', False)),
            'auto_pod_post': bool(getattr(action, 'auto_pod_post', False)),
            'auto_shipment_post': bool(getattr(action, 'auto_shipment_post', False)),
            'auto_treasury_post': bool(getattr(action, 'auto_treasury_post', False)),
            'hard_copy_collection': bool(getattr(action, 'hard_copy_collection', False)),
            'direct_execute': False,
            'requires_evidence_capture': True,
            'capture_mode': 'optional_evidence',
            'shipment_status_impact': (action.shipment_status_impact or '').strip()
            if action
            else '',
            'movement_status_impact': (action.movement_status_impact or '').strip()
            if action
            else '',
            'sequence_category': (getattr(action, 'sequence_category', None) or '').strip()
            if action
            else '',
        },
    )


def resolve_action_category(action) -> str:
    if action is None:
        return ''
    scope = (action.action_scope or '').strip()
    if scope:
        return scope
    return (action.sequence_category or '').strip() or 'job'


def project_allowed_action_row(
    action,
    *,
    request=None,
    current_stage: str = '',
    sort_index: int = 0,
    shipment=None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """
    Mobile allowed-action DTO for one ``TenantOperationAction`` row.
    """
    from mobile_api.helpers.action_navigation_metadata import (
        apply_collect_payment_navigation_to_action_row,
        apply_empty_move_navigation_to_action_row,
        apply_evidence_capture_navigation_to_action_row,
        apply_hard_copy_navigation_to_action_row,
        apply_job_close_navigation_to_action_row,
        apply_pod_upload_navigation,
        apply_standalone_evidence_capture_navigation_to_action_row,
    )
    from iroad_tenants.operation_runtime.movement_action_validator import (
        is_empty_move_catalog_action,
        is_without_scope_catalog_action,
    )
    from mobile_api.helpers.empty_move_action_resolver import action_is_empty_move_lifecycle
    from mobile_api.helpers.job_action_resolver import (
        action_is_collect_payment,
        action_is_job_close,
    )

    name = _localized_action_name(action, request)
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    if is_pod_upload_action(action):
        from mobile_api.execution.evidence.constants import (
            POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
        )
        from mobile_api.pod_capture.policy.pod_capture_policy import (
            build_pod_capture_requirements,
        )
        from mobile_api.pod_capture.services.pod_section_metadata import (
            build_digital_capture_ui,
        )
        from mobile_api.pod_capture.services.pod_capture_action_resolver import (
            digital_action_code_from_action,
        )

        requirements = build_pod_capture_requirements(
            action,
            pod_capture_type='digital',
            shipment=shipment,
        )
        requirements['capture_mode'] = 'digital_evidence'
        requirements['screen'] = 'pod_capture'
        requirements['screen_title'] = 'Capturing Action Evidences'
        requirements['video_max_duration_seconds'] = int(
            requirements.get('video_max_duration_seconds')
            or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
        )
        has_hard_copy_step = bool(getattr(action, 'hard_copy_collection', False))
        digital_code = digital_action_code_from_action(
            action,
            tenant_schema=tenant_schema,
        )
        requirements['capture_ui'] = build_digital_capture_ui(
            requirements,
            has_hard_copy_step=has_hard_copy_step,
            digital_action_code=digital_code,
        )
        row = sync_row_evidence_flags(
            {
                'action_id': str(action.action_id),
                'action_code': action.action_code or '',
                'action_name': name,
                'execution_label': name,
                'action_category': resolve_action_category(action),
                'execution_order': int(action.sequence_number or 0),
                'sort_index': sort_index,
                'current_stage': current_stage,
                'execution_requirements': requirements,
            },
        )
        row['screen'] = 'pod_capture'
        row['action'] = 'go_to_pod_capture'
        row['capture_mode'] = requirements.get('capture_mode') or 'digital_evidence'
        row['screen_title'] = requirements.get('screen_title') or 'Capturing Action Evidences'
        if requirements.get('capture_ui'):
            row['capture_ui'] = requirements['capture_ui']
        return apply_pod_upload_navigation(
            row,
            action,
            shipment=shipment,
            tenant_schema=tenant_schema,
        )

    requirements = build_execution_requirements(action, shipment=shipment)
    row = sync_row_evidence_flags(
        {
            'action_id': str(action.action_id),
            'action_code': action.action_code or '',
            'action_name': name,
            'execution_label': name,
            'action_category': resolve_action_category(action),
            'execution_order': int(action.sequence_number or 0),
            'sort_index': sort_index,
            'current_stage': current_stage,
            'execution_requirements': requirements,
        },
    )

    if _is_hard_copy_action(action):
        return apply_hard_copy_navigation_to_action_row(
            row,
            action,
            shipment=shipment,
            tenant_schema=tenant_schema,
        )

    if action_is_collect_payment(action):
        return apply_collect_payment_navigation_to_action_row(
            row,
            action=action,
            shipment=shipment,
            tenant_schema=tenant_schema,
        )

    if action_is_job_close(action):
        return apply_job_close_navigation_to_action_row(
            row,
            action=action,
        )

    if is_without_scope_catalog_action(action):
        return apply_standalone_evidence_capture_navigation_to_action_row(
            row,
            action=action,
        )

    if is_empty_move_catalog_action(action) or action_is_empty_move_lifecycle(action):
        return apply_empty_move_navigation_to_action_row(
            row,
            action=action,
        )

    return apply_evidence_capture_navigation_to_action_row(row)


def project_allowed_actions_payload(
    actions,
    *,
    request=None,
    current_stage: str = '',
    context_label: str = '',
    job_type: str = '',
    job_id: str = '',
    job_no: str = '',
    shipment=None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Full allowed-actions response from engine queryset (already filtered)."""
    schema = (tenant_schema or '').strip()
    if not schema and request is not None:
        try:
            from mobile_api.job_detail.services.job_detail_driver_resolver import (
                tenant_schema_for_request,
            )

            schema = tenant_schema_for_request(request)
        except Exception:
            schema = ''

    rows = []
    for action in actions:
        rows.append(
            project_allowed_action_row(
                action,
                request=request,
                current_stage=current_stage,
                sort_index=len(rows),
                shipment=shipment,
                tenant_schema=schema,
            )
        )
    primary = rows[0] if rows else None
    return {
        'job_type': job_type,
        'job_id': job_id,
        'job_no': job_no,
        'current_stage': current_stage,
        'context_label': context_label,
        'count': len(rows),
        'actions': rows,
        'primary_action': primary,
        'workflow_source': 'operation_execution.get_allowed_actions',
    }


def resolve_current_stage(*, shipment=None, movement=None) -> str:
    """Reporting-only stage label (not used to filter actions)."""
    if shipment is not None:
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            derive_shipment_execution_stage,
            execution_stage_operational_label,
        )

        stage = derive_shipment_execution_stage(shipment)
        label = execution_stage_operational_label(stage)
        if label:
            return label
        return (getattr(shipment, 'shipment_status', None) or '').strip()
    if movement is not None:
        from iroad_tenants.operation_runtime.movement_stage_derivation import (
            derive_movement_operational_stage,
        )

        label = derive_movement_operational_stage(movement)
        if label:
            return label
        return (getattr(movement, 'status', None) or '').strip()
    return ''
