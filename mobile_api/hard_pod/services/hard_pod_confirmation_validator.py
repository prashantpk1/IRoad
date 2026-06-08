"""
mobile_api/hard_pod/services/hard_pod_confirmation_validator.py

Validate driver page confirmations against Shipment Document checklist rows.
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from mobile_api.hard_pod.exceptions import HardPodError
from mobile_api.hard_pod.services.delivery_note_pages import (
    build_hard_pod_confirmation_context,
)


def _page_key(page: dict[str, Any]) -> tuple[str, str]:
    page_id = (page.get('page_id') or '').strip()
    if page_id:
        return ('page_id', page_id)
    document_id = (page.get('document_id') or '').strip()
    line_no = str(int(page.get('line_no') or 0))
    return ('line', f'{document_id}:{line_no}')


def validate_confirmed_pages(
    shipment: Any,
    confirmed_pages: list[dict[str, Any]] | None,
    *,
    tenant_schema: str,
) -> list[dict[str, Any]]:
    """
    Ensure every expected DN page is explicitly confirmed before custody submit.

    Raises:
        HardPodError: Missing pages or unknown page tokens.
    """
    context = build_hard_pod_confirmation_context(
        shipment,
        tenant_schema=tenant_schema,
    )
    expected_pages = list(context.get('pages') or [])
    if not expected_pages:
        raise HardPodError(
            str(_('mobile.hard_pod.no_confirmation_pages')),
            code='no_confirmation_pages',
            http_status=400,
            message_key='mobile.hard_pod.no_confirmation_pages',
        )

    submitted = list(confirmed_pages or [])
    if not submitted:
        raise HardPodError(
            str(_('mobile.hard_pod.confirmed_pages_required')),
            code='confirmed_pages_required',
            http_status=400,
            message_key='mobile.hard_pod.confirmed_pages_required',
        )

    expected_by_key = {_page_key(page): page for page in expected_pages}
    submitted_keys: set[tuple[str, str]] = set()

    for row in submitted:
        if not isinstance(row, dict):
            continue
        if row.get('confirmed') is False:
            continue
        key = _page_key(row)
        if key not in expected_by_key:
            raise HardPodError(
                str(_('mobile.hard_pod.confirmed_page_unknown')),
                code='confirmed_page_unknown',
                http_status=400,
                message_key='mobile.hard_pod.confirmed_page_unknown',
            )
        submitted_keys.add(key)

    missing = [key for key in expected_by_key if key not in submitted_keys]
    if missing:
        raise HardPodError(
            str(_('mobile.hard_pod.confirmed_pages_incomplete')),
            code='confirmed_pages_incomplete',
            http_status=400,
            message_key='mobile.hard_pod.confirmed_pages_incomplete',
        )

    normalized: list[dict[str, Any]] = []
    for key in expected_by_key:
        expected = expected_by_key[key]
        normalized.append(
            {
                'page_id': (expected.get('page_id') or '').strip(),
                'document_id': (expected.get('document_id') or '').strip(),
                'line_no': int(expected.get('line_no') or 0),
                'label': (expected.get('label') or '').strip(),
                'physical_page_no': int(expected.get('physical_page_no') or 0),
            }
        )
    return normalized
