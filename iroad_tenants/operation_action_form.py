"""Operation Action Master form rules — PCS §9.1–§9.3."""
from __future__ import annotations

import re

from iroad_tenants.status_impact_resolution import (
    STATUS_IMPACT_DO_NOTHING_LABEL,
    STATUS_IMPACT_DO_NOTHING_VALUE,
    canonical_booking_status_impact_value,
    canonical_movement_status_impact_value,
    canonical_shipment_status_impact_value,
    is_valid_booking_status_impact,
    is_valid_movement_status_impact,
    is_valid_shipment_status_impact,
    operation_action_booking_status_choices,
    operation_action_movement_status_choices,
    operation_action_shipment_status_choices,
)

ACTION_SCOPE_CHOICES = [
    ('job', 'Job'),
    ('on_call', 'On Call'),
    ('without', 'Without'),
]

SEQUENCE_CATEGORY_CHOICES = [
    ('job', 'Job'),
    ('empty_move', 'Empty Move'),
    ('without', 'Without'),
]

SEQUENCED_ACTION_SCOPES = frozenset({'job', 'on_call'})
SEQUENCED_CATEGORIES = frozenset({'job', 'empty_move'})
VALID_ACTION_SCOPES = frozenset(scope for scope, _ in ACTION_SCOPE_CHOICES)
VALID_SEQUENCE_CATEGORIES = frozenset(cat for cat, _ in SEQUENCE_CATEGORY_CHOICES)
OA_ACTION_CODE_PATTERN = re.compile(r'^OA-(\d+)$', re.IGNORECASE)
JOB_ACTION_CODE_PREFIX = 'OA'
OPERATION_ACTION_AUTO_FORM_CODE = 'operation-actions'

EXCLUSIVE_MAX_ONE_TOGGLES = {
    'auto_shipment_post': 'Auto Shipment Post',
    'auto_pod_post': 'Auto POD Post',
    'hard_copy_collection': 'Hard Copy Collection',
    'auto_treasury_post': 'Confirm Payment',
}
REQUIRED_EXACTLY_ONE_TOGGLE = 'auto_movement_post'
REQUIRED_EXACTLY_ONE_TOGGLE_LABEL = 'Auto Movement Post'
SINGLETON_TOGGLE_FIELDS = (
    REQUIRED_EXACTLY_ONE_TOGGLE,
    *EXCLUSIVE_MAX_ONE_TOGGLES.keys(),
)

OPERATION_IMPACT_FIELDS = (
    'auto_movement_post',
    'auto_shipment_post',
    'auto_pod_post',
    'hard_copy_collection',
    'auto_treasury_post',
    'booking_status_impact',
    'shipment_status_impact',
    'movement_status_impact',
)


def count_toggle_enabled(
    field_name: str,
    *,
    exclude_action_id=None,
    exclude_action_ids=None,
    sequence_category: str | None = None,
) -> int:
    from tenant_workspace.models import TenantOperationAction

    qs = TenantOperationAction.objects.filter(**{field_name: True})
    category = (sequence_category or '').strip()
    if field_name == REQUIRED_EXACTLY_ONE_TOGGLE and category in SEQUENCED_CATEGORIES:
        qs = qs.filter(sequence_category=category)
    excluded = set()
    if exclude_action_id:
        excluded.add(exclude_action_id)
    for action_id in exclude_action_ids or ():
        if action_id:
            excluded.add(action_id)
    if excluded:
        qs = qs.exclude(action_id__in=excluded)
    return qs.count()


def default_auto_movement_post_enabled(
    *,
    exclude_action_id=None,
    sequence_category: str = 'job',
) -> bool:
    """Default ON when no other action in the same Sequence Category owns Auto Movement Post."""
    category = (sequence_category or '').strip()
    if category not in SEQUENCED_CATEGORIES:
        return False
    return count_toggle_enabled(
        REQUIRED_EXACTLY_ONE_TOGGLE,
        exclude_action_id=exclude_action_id,
        sequence_category=category,
    ) == 0


def default_mobile_visible_for_action_scope(action_scope: str) -> bool:
    """
    Portal-created actions: driver-facing scopes default to mobile-visible.

    Internal ``without`` (cancel/reversal) actions stay hidden from the driver app.
    """
    scope = (action_scope or '').strip().casefold()
    if scope == 'without':
        return False
    return scope in {'job', 'on_call'}


def validate_configuration_toggles(
    form_data: dict,
    *,
    exclude_action_id=None,
    exclude_action_ids=None,
    enabled_counts: dict[str, int] | None = None,
) -> dict[str, str]:
    """PCS §9.2 — singleton toggle limits across Operation Action Master."""
    form_errors: dict[str, str] = {}
    excluded_ids = [value for value in (exclude_action_ids or ()) if value]
    category = (form_data.get('sequence_category') or '').strip()
    movement_category_scoped = category in SEQUENCED_CATEGORIES
    if enabled_counts is None:
        enabled_counts = {
            REQUIRED_EXACTLY_ONE_TOGGLE: count_toggle_enabled(
                REQUIRED_EXACTLY_ONE_TOGGLE,
                exclude_action_id=exclude_action_id,
                exclude_action_ids=excluded_ids,
                sequence_category=category if movement_category_scoped else None,
            ),
            **{
                field_name: count_toggle_enabled(
                    field_name,
                    exclude_action_id=exclude_action_id,
                    exclude_action_ids=excluded_ids,
                )
                for field_name in EXCLUSIVE_MAX_ONE_TOGGLES
            },
        }

    movement_enabled = bool(form_data.get(REQUIRED_EXACTLY_ONE_TOGGLE))
    other_movement_count = enabled_counts.get(REQUIRED_EXACTLY_ONE_TOGGLE, 0)
    if movement_category_scoped:
        if movement_enabled and other_movement_count > 0:
            form_errors[REQUIRED_EXACTLY_ONE_TOGGLE] = (
                f'Only one action per Sequence Category can have '
                f'{REQUIRED_EXACTLY_ONE_TOGGLE_LABEL} enabled.'
            )
        elif not movement_enabled and other_movement_count == 0:
            form_errors[REQUIRED_EXACTLY_ONE_TOGGLE] = (
                f'Exactly one action per Sequence Category must have '
                f'{REQUIRED_EXACTLY_ONE_TOGGLE_LABEL} enabled.'
            )

    for field_name, label in EXCLUSIVE_MAX_ONE_TOGGLES.items():
        if not form_data.get(field_name):
            continue
        if enabled_counts.get(field_name, 0) > 0:
            form_errors[field_name] = f'Only one action can have {label} enabled.'

    return form_errors


def validate_status_impact_fields(form_data: dict) -> dict[str, str]:
    """PCS §9.3 — optional status impacts; empty value means Do Nothing."""
    form_errors: dict[str, str] = {}

    booking_value = (form_data.get('booking_status_impact') or '').strip()
    if booking_value and not is_valid_booking_status_impact(booking_value):
        form_errors['booking_status_impact'] = 'Invalid booking status impact selected.'
    else:
        form_data['booking_status_impact'] = canonical_booking_status_impact_value(
            booking_value
        )

    shipment_value = (form_data.get('shipment_status_impact') or '').strip()
    if shipment_value and not is_valid_shipment_status_impact(shipment_value):
        form_errors['shipment_status_impact'] = 'Invalid shipment status impact selected.'
    else:
        form_data['shipment_status_impact'] = canonical_shipment_status_impact_value(
            shipment_value
        )

    movement_value = (form_data.get('movement_status_impact') or '').strip()
    if movement_value and not is_valid_movement_status_impact(movement_value):
        form_errors['movement_status_impact'] = 'Invalid movement status impact selected.'
    else:
        form_data['movement_status_impact'] = canonical_movement_status_impact_value(
            movement_value
        )

    return form_errors


def sequence_category_field_active(action_scope: str) -> bool:
    """Sequence Category applies only when Action Scope is Job or On Call."""
    return (action_scope or '').strip() in SEQUENCED_ACTION_SCOPES


def sequence_number_field_active(action_scope: str, sequence_category: str) -> bool:
    """Sequence Number applies when scope is Job/On Call and category is not Without."""
    if not sequence_category_field_active(action_scope):
        return False
    return (sequence_category or '').strip() in SEQUENCED_CATEGORIES


def sequencing_is_active(action_scope: str, sequence_category: str) -> bool:
    return sequence_number_field_active(action_scope, sequence_category)


def normalize_operation_action_sequencing(form_data: dict) -> dict:
    """Clear sequencing values when PCS activation rules disable them."""
    scope = (form_data.get('action_scope') or '').strip()
    if scope == 'without':
        form_data['sequence_category'] = 'without'
        form_data['sequence_number'] = '1'
        return form_data

    category = (form_data.get('sequence_category') or '').strip()
    if not sequence_category_field_active(scope):
        form_data['sequence_category'] = ''
        form_data['sequence_number'] = '1'
        return form_data

    if category == 'without':
        form_data['sequence_category'] = ''
        form_data['sequence_number'] = '1'
        return form_data

    if category not in SEQUENCED_CATEGORIES:
        form_data['sequence_number'] = '1'
    return form_data


def validate_consecutive_sequence_numbers(numbers: list[int]) -> str | None:
    """PCS §9.1.1.2 — numbers must be 1..N with no gaps or duplicates."""
    if not numbers:
        return 'Sequence Number is required.'
    unique = sorted(set(numbers))
    if len(unique) != len(numbers):
        return (
            'Sequence Number must be unique within the selected Sequence Category.'
        )
    if unique != list(range(1, unique[-1] + 1)):
        return (
            'Sequence numbers must start at 1 and increase consecutively with no gaps '
            'within the selected Sequence Category.'
        )
    return None


def existing_sequenced_numbers(sequence_category: str, *, exclude_action_id=None):
    from tenant_workspace.models import TenantOperationAction

    if sequence_category not in SEQUENCED_CATEGORIES:
        return []
    qs = TenantOperationAction.objects.filter(
        sequence_category=sequence_category,
        action_scope__in=SEQUENCED_ACTION_SCOPES,
    )
    if exclude_action_id:
        qs = qs.exclude(action_id=exclude_action_id)
    return [int(value) for value in qs.values_list('sequence_number', flat=True)]


def operation_impact_snapshot(action) -> dict:
    return {field: getattr(action, field) for field in OPERATION_IMPACT_FIELDS}


def operation_impact_from_form(form_data: dict) -> dict:
    return {field: form_data.get(field) for field in OPERATION_IMPACT_FIELDS}


def find_sequence_peer(sequence_category: str, sequence_number: int, *, exclude_action_id=None):
    from tenant_workspace.models import TenantOperationAction

    if sequence_category not in SEQUENCED_CATEGORIES:
        return None
    qs = TenantOperationAction.objects.filter(
        sequence_category=sequence_category,
        sequence_number=sequence_number,
        action_scope__in=SEQUENCED_ACTION_SCOPES,
    )
    if exclude_action_id:
        qs = qs.exclude(action_id=exclude_action_id)
    return qs.first()


def recommended_sequence_number(sequence_category: str, *, exclude_action_id=None) -> int:
    """Next consecutive slot for a new/edited action in the category (PCS §9.1.1.2)."""
    numbers = sorted(
        existing_sequenced_numbers(
            sequence_category,
            exclude_action_id=exclude_action_id,
        )
    )
    if not numbers:
        return 1
    return numbers[-1] + 1


def _max_existing_oa_action_suffix() -> int:
    from tenant_workspace.models import TenantOperationAction

    max_suffix = 0
    for code in TenantOperationAction.objects.filter(
        action_code__istartswith=f'{JOB_ACTION_CODE_PREFIX}-',
    ).values_list('action_code', flat=True):
        match = OA_ACTION_CODE_PATTERN.match((code or '').strip())
        if match:
            max_suffix = max(max_suffix, int(match.group(1)))
    return max_suffix


def format_job_operation_action_code(sequence_number: int) -> str:
    return f'{JOB_ACTION_CODE_PREFIX}-{int(sequence_number):04d}'


def recommended_operation_action_code(sequence_category: str, *, exclude_action_id=None) -> str:
    """Preview next OA code aligned with the next job sequence slot."""
    if sequence_category != 'job':
        return ''
    seq = recommended_sequence_number('job', exclude_action_id=exclude_action_id)
    seq = max(seq, _max_existing_oa_action_suffix() + 1)
    return format_job_operation_action_code(seq)


def resolve_operation_action_code(sequence_category: str, sequence_number: int) -> str | None:
    """Use OA-{seq:04d} for job actions when the code slot is still free."""
    if sequence_category != 'job':
        return None
    from tenant_workspace.models import TenantOperationAction

    candidate = format_job_operation_action_code(sequence_number)
    if TenantOperationAction.objects.filter(action_code__iexact=candidate).exists():
        return None
    return candidate


def sync_operation_action_auto_number_sequence() -> int:
    """Keep the OA auto-number counter at or above the next sequential slot."""
    from tenant_workspace.models import AutoNumberSequence

    next_required = max(_max_existing_oa_action_suffix() + 1, 1)
    sequence, _ = AutoNumberSequence.objects.get_or_create(
        form_code=OPERATION_ACTION_AUTO_FORM_CODE,
        defaults={'next_number': next_required},
    )
    current = int(sequence.next_number or 1)
    if current < next_required:
        sequence.next_number = next_required
        sequence.save(update_fields=['next_number', 'updated_at'])
        return next_required
    return current


def allocate_operation_action_code(
    sequence_category: str,
    sequence_number: int,
) -> str | None:
    """Pick the next sequential OA code for job actions before auto-number fallback."""
    code = resolve_operation_action_code(sequence_category, sequence_number)
    if code:
        return code
    if sequence_category != 'job':
        return None
    next_code = recommended_operation_action_code('job')
    if not next_code:
        return None
    from tenant_workspace.models import TenantOperationAction

    if TenantOperationAction.objects.filter(action_code__iexact=next_code).exists():
        return None
    return next_code


def validate_category_sequence_integrity(sequence_category: str) -> str | None:
    """Ensure all actions in a category use consecutive numbering 1..N."""
    if sequence_category not in SEQUENCED_CATEGORIES:
        return None
    numbers = existing_sequenced_numbers(sequence_category)
    if not numbers:
        return None
    return validate_consecutive_sequence_numbers(numbers)


def repack_sequence_category(sequence_category: str) -> None:
    """Renumber actions in a category to 1..N with no gaps (PCS §9.1.1.2)."""
    from tenant_workspace.models import TenantOperationAction

    if sequence_category not in SEQUENCED_CATEGORIES:
        return
    actions = list(
        TenantOperationAction.objects.filter(
            sequence_category=sequence_category,
            action_scope__in=SEQUENCED_ACTION_SCOPES,
        ).order_by('sequence_number', 'action_code')
    )
    for index, action in enumerate(actions, start=1):
        if int(action.sequence_number or 0) != index:
            action.sequence_number = index
            action.save(update_fields=['sequence_number', 'updated_at'])


def next_sequence_slot(sequence_category: str, *, exclude_action_ids=None) -> int:
    from tenant_workspace.models import TenantOperationAction

    exclude_action_ids = [value for value in (exclude_action_ids or []) if value]
    qs = TenantOperationAction.objects.filter(
        sequence_category=sequence_category,
        action_scope__in=SEQUENCED_ACTION_SCOPES,
    )
    full_numbers = [int(value) for value in qs.values_list('sequence_number', flat=True)]
    if not full_numbers:
        return 1
    remaining_qs = qs
    for action_id in exclude_action_ids:
        remaining_qs = remaining_qs.exclude(action_id=action_id)
    remaining_numbers = [
        int(value) for value in remaining_qs.values_list('sequence_number', flat=True)
    ]
    if not remaining_numbers:
        return max(full_numbers) + 1
    return max(remaining_numbers) + 1


def operation_action_sequence_registry() -> dict:
    """Map sequence category -> assigned sequence rows for client-side conflict checks."""
    from tenant_workspace.models import TenantOperationAction

    qs = TenantOperationAction.objects.filter(
        sequence_category__in=SEQUENCED_CATEGORIES,
        action_scope__in=SEQUENCED_ACTION_SCOPES,
    ).order_by('sequence_category', 'sequence_number', 'action_code')
    registry: dict[str, list[dict]] = {}
    for row in qs:
        registry.setdefault(row.sequence_category, []).append(
            {
                'action_id': str(row.action_id),
                'sequence_number': int(row.sequence_number or 1),
                'english_label': row.english_label,
                'action_code': row.action_code,
            }
        )
    return registry


def resolve_sequence_swap_peer(
    form_data: dict,
    sequence_number: int,
    *,
    exclude_action_id=None,
):
    """Return the peer occupying *sequence_number* when swap is confirmed."""
    if not form_data.get('confirm_sequence_swap'):
        return None
    scope = (form_data.get('action_scope') or '').strip()
    category = (form_data.get('sequence_category') or '').strip()
    if not sequencing_is_active(scope, category):
        return None
    return find_sequence_peer(
        category,
        sequence_number,
        exclude_action_id=exclude_action_id,
    )


def apply_confirmed_sequence_swap(*, peer, current_action, form_data: dict) -> None:
    """
    Before saving the current action, move the conflicting peer out of the slot.
    Edit: peer receives the current action's previous sequence number (pairwise swap).
          Operation Impact toggles stay on each action.
    Create: peer moves to the next free sequence slot with all singleton toggles OFF.
             Each singleton toggle enabled on the new action is turned OFF on every
             other action so ownership transfers to the record being created.
    """
    category = (form_data.get('sequence_category') or '').strip()
    peer_update_fields = ['sequence_number', 'updated_at']

    if current_action is not None:
        peer.sequence_number = int(current_action.sequence_number or 1)
        peer.save(update_fields=peer_update_fields)
        return

    peer.sequence_number = next_sequence_slot(
        category,
        exclude_action_ids=[peer.pk],
    )
    for field_name in SINGLETON_TOGGLE_FIELDS:
        if getattr(peer, field_name, False):
            setattr(peer, field_name, False)
            peer_update_fields.append(field_name)
    peer.save(update_fields=peer_update_fields)

    from tenant_workspace.models import TenantOperationAction

    for field_name in SINGLETON_TOGGLE_FIELDS:
        if not form_data.get(field_name):
            continue
        others = TenantOperationAction.objects.filter(**{field_name: True}).exclude(
            pk=peer.pk,
        )
        if (
            field_name == REQUIRED_EXACTLY_ONE_TOGGLE
            and category in SEQUENCED_CATEGORIES
        ):
            others = others.filter(sequence_category=category)
        for other in others:
            setattr(other, field_name, False)
            other.save(update_fields=[field_name, 'updated_at'])


def validate_sequence_number_placement(
    sequence_category: str,
    sequence_number: int,
    *,
    exclude_action_id=None,
    confirm_swap: bool = False,
) -> str | None:
    """PCS §9.1.1.2 — placement must keep 1..N consecutive within the category."""
    if sequence_category not in SEQUENCED_CATEGORIES:
        return None

    peer = find_sequence_peer(
        sequence_category,
        sequence_number,
        exclude_action_id=exclude_action_id,
    )
    if peer and not confirm_swap:
        return (
            f'Sequence {sequence_number} is already used by '
            f'"{peer.english_label}". Confirm swap to exchange sequence numbers.'
        )

    if peer and confirm_swap:
        return None

    existing = existing_sequenced_numbers(
        sequence_category,
        exclude_action_id=exclude_action_id,
    )
    next_slot = recommended_sequence_number(
        sequence_category,
        exclude_action_id=exclude_action_id,
    )
    if sequence_number > next_slot:
        return (
            f'Sequence Number must be the next available value ({next_slot}) '
            f'or an existing slot via swap. Gaps are not allowed within '
            f'{sequence_category.replace("_", " ").title()}.'
        )

    combined = existing + [sequence_number]
    return validate_consecutive_sequence_numbers(combined)


def validate_operation_action_sequencing(
    form_data: dict,
    *,
    exclude_action_id=None,
) -> tuple[dict, int]:
    """Validate scope/category/number fields and return (errors, sequence_number)."""
    form_errors: dict[str, str] = {}
    normalize_operation_action_sequencing(form_data)

    scope = (form_data.get('action_scope') or '').strip()
    category = (form_data.get('sequence_category') or '').strip()

    if not scope:
        form_errors['action_scope'] = 'Action Scope is required.'
    elif scope not in VALID_ACTION_SCOPES:
        form_errors['action_scope'] = 'Invalid action scope selected.'

    sequence_number = 1
    if sequence_category_field_active(scope):
        if not category:
            form_errors['sequence_category'] = 'Sequence Category is required.'
        elif category == 'without':
            form_errors['sequence_category'] = (
                'Select Job or Empty Move when Action Scope is Job or On Call.'
            )
        elif category not in VALID_SEQUENCE_CATEGORIES:
            form_errors['sequence_category'] = 'Invalid sequence category selected.'
        elif category not in SEQUENCED_CATEGORIES:
            form_errors['sequence_category'] = (
                'Select Job or Empty Move when Action Scope is Job or On Call.'
            )

        if sequencing_is_active(scope, category):
            raw_number = (form_data.get('sequence_number') or '').strip()
            if not raw_number:
                form_errors['sequence_number'] = 'Sequence Number is required.'
            else:
                try:
                    sequence_number = int(raw_number)
                    if sequence_number < 1:
                        raise ValueError
                except ValueError:
                    form_errors['sequence_number'] = (
                        'Sequence Number must be a whole number of 1 or greater.'
                    )
                    sequence_number = 1

            if (
                category in SEQUENCED_CATEGORIES
                and 'sequence_number' not in form_errors
            ):
                confirm_swap = bool(form_data.get('confirm_sequence_swap'))
                placement_error = validate_sequence_number_placement(
                    category,
                    sequence_number,
                    exclude_action_id=exclude_action_id,
                    confirm_swap=confirm_swap,
                )
                if placement_error:
                    form_errors['sequence_number'] = placement_error

    return form_errors, sequence_number
