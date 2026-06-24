"""Promote pending Hard POD custody during kernel side effects (before Delivered gate)."""

from __future__ import annotations

from typing import Any

from django.db import connection, transaction
from django_tenants.utils import schema_context

from iroad_tenants.operation_execution import _pending_hard_pod_custody_exists


def _confirmed_pages_payload(submission: Any) -> list[dict[str, Any]]:
    return [
        {
            'page_id': (row.page_id or '').strip(),
            'document_id': (row.document_id or '').strip(),
            'line_no': row.line_no,
            'physical_page_no': row.physical_page_no,
            'label': (row.label or '').strip(),
        }
        for row in submission.confirmed_pages.order_by('line_no', 'created_at')
    ]


def _resolve_submission_for_action_log(action_log: Any) -> Any | None:
    from mobile_api.hard_pod.models import HardPODCustodySubmission
    from mobile_api.hard_pod.services.hard_pod_idempotency_service import (
        HardPodIdempotencyService,
    )

    shipment_id = str(getattr(action_log, 'shipment_id', None) or '').strip()
    if not shipment_id:
        return None

    driver = getattr(action_log, 'driver', None)
    driver_id = str(getattr(driver, 'pk', None) or getattr(driver, 'driver_id', '') or '').strip()
    tenant_schema = (getattr(connection, 'schema_name', None) or '').strip()
    custody_submission_id = str(
        getattr(action_log, '_hard_pod_custody_submission_id', None) or ''
    ).strip()
    client_submission_id = str(
        getattr(action_log, '_hard_pod_client_submission_id', None) or ''
    ).strip()

    if custody_submission_id:
        return (
            HardPODCustodySubmission.objects.filter(
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                shipment_id=shipment_id,
                pk=custody_submission_id,
            )
            .first()
        )

    if client_submission_id:
        existing = HardPodIdempotencyService().get_by_client_submission(
            tenant_schema=tenant_schema,
            driver_id=driver_id,
            client_submission_id=client_submission_id,
        )
        if existing is not None and (existing.shipment_id or '').strip() == shipment_id:
            return existing

    return (
        HardPODCustodySubmission.objects.filter(
            shipment_id=shipment_id,
            promoted_at__isnull=True,
        )
        .order_by('-created_at')
        .first()
    )


def promote_pending_hard_pod_custody_for_action_log(
    *,
    action_log: Any,
    shipment: Any,
    action: Any,
    created_by_label: str = '',
) -> bool:
    """
    Promote unpromoted Hard POD custody before shipment moves to Delivered.

  Hard-first mobile flow submits custody via ``/hard-pod/submit/`` then executes
    a combined POD action (e.g. OA-0008) without digital evidence yet.
    """
    if action_log is None or shipment is None or action is None:
        return False
    if not getattr(action, 'hard_copy_collection', False):
        return False
    from iroad_tenants.operation_field_catalog import operation_shipment_uses_hard_copy_pod

    if not operation_shipment_uses_hard_copy_pod(shipment):
        return False
    if not _pending_hard_pod_custody_exists(shipment):
        return False

    submission = _resolve_submission_for_action_log(action_log)
    if submission is None:
        return False

    action_log_id = str(
        getattr(action_log, 'log_id', None) or getattr(action_log, 'pk', '') or ''
    ).strip()
    if not action_log_id:
        return False

    if submission.promotion_action_log_id == action_log_id:
        return True

    if submission.promoted_at and submission.promotion_action_log_id != action_log_id:
        return False

    confirmed_pages = _confirmed_pages_payload(submission)
    tenant_schema = (submission.tenant_schema or getattr(connection, 'schema_name', None) or '').strip()

    from iroad_tenants.operation_runtime.pod_action import (
        apply_a7h_hard_pod_physical_posting,
    )

    with schema_context(tenant_schema) if tenant_schema else schema_context(connection.schema_name):
        apply_a7h_hard_pod_physical_posting(
            action_log=action_log,
            shipment=shipment,
            confirmed_pages=confirmed_pages,
            tenant_schema=tenant_schema,
        )

    with transaction.atomic():
        submission.promoted_at = submission.promoted_at or getattr(action_log, 'log_date', None)
        submission.promotion_action_log_id = action_log_id
        submission.save(update_fields=['promoted_at', 'promotion_action_log_id'])

    return True
