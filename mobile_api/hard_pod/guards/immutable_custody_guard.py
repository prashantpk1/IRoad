"""
mobile_api/hard_pod/guards/immutable_custody_guard.py

Custody immutability guard for Hard POD custody header rows.

Rules:
1. HardPODCustodySubmission events/media are append-only (enforced by models).
2. The submission header becomes effectively immutable once custody is verified.
3. The only allowed mutation after verification is the one-time Execute promotion
   linkage (set promoted_at + promotion_action_log_id).
"""

from __future__ import annotations

from typing import Iterable

from mobile_api.hard_pod.models import (
    HardPODCustodySubmission,
    HardPODCustodySubmissionEvent,
)


def _allowed_promotion_fields(update_fields: Iterable[str] | None) -> bool:
    if update_fields is None:
        return False
    allowed = {'promoted_at', 'promotion_action_log_id'}
    uf = {str(x) for x in update_fields}
    return uf.issubset(allowed) and bool(uf & allowed)


def assert_custody_header_mutable(
    submission: HardPODCustodySubmission,
    *,
    update_fields: Iterable[str] | None = None,
) -> None:
    """
    Raise ValueError when a custody header update violates immutability rules.

    This guard is intentionally strict; it relies on consumers updating only the
    promotion fields with `update_fields=[...]`.
    """
    if not getattr(submission, 'pk', None):
        return

    existing = HardPODCustodySubmission.objects.filter(pk=submission.pk).first()
    if existing is None:
        return

    # Once promoted, never allow any further updates to the header.
    if bool(getattr(existing, 'promoted_at', None)) or bool(
        str(getattr(existing, 'promotion_action_log_id', '') or '').strip()
    ):
        raise ValueError('Hard POD custody submission is immutable after promotion.')

    # Once verified, allow only promotion linkage updates.
    verified_exists = HardPODCustodySubmissionEvent.objects.filter(
        submission_id=submission.pk,
        event_type=HardPODCustodySubmissionEvent.EventType.VERIFIED,
    ).exists()
    if verified_exists and not _allowed_promotion_fields(update_fields):
        raise ValueError(
            'Hard POD custody submission header is immutable after verified.'
        )

