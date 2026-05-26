"""
mobile_api/execution/evidence/action_log_media_persistence.py

Shared Action Log media row persistence (portal + mobile execute).

Extracted from ``iroad_tenants.views._tenant_operation_action_log_save_media_from_request``
so mobile can persist JSON ``media[]`` payloads in the same transactional pattern.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, BinaryIO

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from mobile_api.execution.evidence.constants import (
    MEDIA_DESCRIPTION_MAX_LENGTH,
    MEDIA_TYPE_MAX_LENGTH,
)
from tenant_workspace.models import TenantOperationActionMedia


@dataclass
class ActionLogMediaItem:
    """One evidence attachment for ``TenantOperationActionMedia``."""

    media_type: str = ''
    description: str = ''
    captured_at: datetime | None = None
    media_id: str = ''
    file_ref: str = ''
    file_name: str = ''
    line_no: int = 0
    upload: Any | None = field(default=None, repr=False)


def normalize_media_items(raw_items: list[Any] | None) -> list[ActionLogMediaItem]:
    """Map mobile API ``media[]`` dicts to persistence rows."""
    if not raw_items:
        return []
    normalized: list[ActionLogMediaItem] = []
    for idx, row in enumerate(raw_items):
        if not isinstance(row, dict):
            continue
        media_type = str(row.get('media_type') or '').strip().casefold()
        captured_at = None
        captured_raw = str(
            row.get('captured_at') or row.get('timestamp') or ''
        ).strip()
        if captured_raw:
            captured_at = parse_datetime(captured_raw)
            if captured_at is not None and timezone.is_naive(captured_at):
                captured_at = timezone.make_aware(
                    captured_at,
                    timezone.get_current_timezone(),
                )
        normalized.append(
            ActionLogMediaItem(
                media_type=media_type,
                description=str(row.get('description') or '').strip(),
                captured_at=captured_at,
                media_id=str(row.get('media_id') or '').strip(),
                file_ref=str(row.get('file_ref') or '').strip(),
                file_name=str(row.get('file_name') or '').strip(),
                line_no=int(row.get('sort_order') or row.get('line_no') or (idx + 1)),
                upload=row.get('file'),
            )
        )
    return normalized


def _coerce_uuid(value: str) -> uuid.UUID | None:
    token = (value or '').strip()
    if not token:
        return None
    try:
        return uuid.UUID(token)
    except (TypeError, ValueError, AttributeError):
        return None


def persist_action_log_media_rows(
    action_log,
    items: list[ActionLogMediaItem],
    *,
    replace_existing: bool = True,
) -> list[Any]:
    """
    Create or update ``TenantOperationActionMedia`` rows for one Action Log.

    Mirrors portal replace semantics: rows not in ``kept_ids`` are deleted when
    ``replace_existing`` is True (same as portal evidence attachment save).

    Must run inside the caller's ``transaction.atomic`` — rolls back with execute.
    """
    if action_log is None:
        return []

    kept_ids: set[Any] = set()
    line_no = 0
    created_ids: list[Any] = []

    for item in items:
        media_type = (item.media_type or '').strip().casefold()[:MEDIA_TYPE_MAX_LENGTH]
        description = (item.description or '')[:MEDIA_DESCRIPTION_MAX_LENGTH]
        upload = item.upload

        existing = None
        if item.media_id:
            parsed_id = _coerce_uuid(item.media_id)
            if parsed_id is not None:
                existing = action_log.media_rows.filter(pk=parsed_id).first()

        has_payload = any(
            [
                media_type,
                description,
                item.captured_at,
                item.file_ref,
                item.file_name,
                upload,
            ]
        )
        if existing is None and not has_payload:
            continue

        line_no += 1
        captured_at = item.captured_at

        if existing is not None:
            existing.line_no = line_no
            if media_type:
                existing.media_type = media_type
            if description:
                existing.description = description
            if captured_at is not None:
                existing.captured_at = captured_at
            if upload is not None:
                existing.file = upload
            elif item.file_ref and not existing.file:
                existing.file.name = item.file_ref
            existing.save()
            kept_ids.add(existing.pk)
            created_ids.append(existing.pk)
            continue

        if not has_payload:
            continue

        media_obj = TenantOperationActionMedia(
            action_log=action_log,
            line_no=line_no,
            media_type=media_type,
            description=description,
            captured_at=captured_at,
        )
        if upload is not None:
            media_obj.file = upload
        elif item.file_ref:
            media_obj.file.name = item.file_ref
        media_obj.save()
        kept_ids.add(media_obj.pk)
        created_ids.append(media_obj.pk)

    if replace_existing:
        if kept_ids:
            action_log.media_rows.exclude(pk__in=kept_ids).delete()
        elif items:
            action_log.media_rows.all().delete()

    return created_ids
