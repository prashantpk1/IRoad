"""
iroad_tenants/services/treasury_side_effects.py

Execute Action is the *only* authority for treasury mutations. This module provides
small, idempotent helpers used during Action side effects to bind staged mobile
evidence (e.g. payment collection bundles) to the Action Log that consumed it.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils import timezone


def consume_payment_collection_bundle_for_action9(*, bundle, action_log) -> None:
    """
    Bind a staged PaymentCollectionBundle to the Action Log that consumed it.

    Replay/dup safety:
    - If already consumed by the same Action Log → no-op
    - If already consumed by a different Action Log → reject (prevents reuse)
    """
    if bundle is None or action_log is None:
        return

    action_log_id = getattr(action_log, 'pk', None) or getattr(action_log, 'log_id', None)
    if not action_log_id:
        return

    existing = getattr(bundle, 'promotion_action_log_id', None)
    if existing:
        if str(existing) == str(action_log_id):
            return
        raise ValidationError('Payment bundle already consumed by another execution.')

    # Mark consumption (evidence linkage, not workflow mutation).
    bundle.promoted_at = timezone.now()
    bundle.promotion_action_log_id = action_log_id
    bundle.save(update_fields=['promoted_at', 'promotion_action_log_id'])

    # Forensic audit linkage (best-effort).
    try:
        from mobile_api.payment_collection.models import PaymentCollectionAudit

        execution_idempotency_key = str(
            getattr(action_log, 'idempotency_key', '') or ''
        ).strip()
        # Only fill blank audits; reject conflicting linkage.
        audits = PaymentCollectionAudit.objects.filter(bundle=bundle)
        for audit in audits:
            current = (getattr(audit, 'action_log_id', '') or '').strip()
            if current and str(current) != str(action_log_id):
                raise ValidationError('Payment audit already linked to another action log.')
        audits.update(
            action_log_id=action_log_id,
            execution_idempotency_key=execution_idempotency_key,
            promoted_at=timezone.now(),
        )
    except Exception:
        # Evidence linkage to bundle is the primary invariant for replay safety.
        # Audit linkage should not block treasury mutation in production pipelines.
        pass

