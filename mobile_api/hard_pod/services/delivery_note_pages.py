"""
mobile_api/hard_pod/services/delivery_note_pages.py

Delivery-note page lines for Hard POD physical custody confirmation (mobile checklist).

Source of truth: ``TenantShipmentDocument`` rows with ``is_delivery_note=True`` and
their ``TenantShipmentDocumentPage`` subform (IRoute Ch. 6).
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import ProgrammingError
from django_tenants.utils import schema_context

logger = logging.getLogger('mobile_api.hard_pod.pages')


def build_hard_pod_confirmation_context(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    limit: int = 50,
) -> dict[str, Any]:
    """
    Shipment Documents + page checklist for Hard POD Collection Confirmation UI.

    Returns::

        {
            "documents": [{document header + pages[]}, ...],
            "pages": [flat page rows for backward-compatible clients],
        }
    """
    if shipment is None:
        return {'documents': [], 'pages': []}

    schema = (tenant_schema or getattr(shipment, 'tenant_schema', None) or '').strip()
    if not schema:
        documents = [_synthetic_document_from_shipment(shipment, limit=limit)]
        pages = _flatten_pages(documents)
        return {'documents': documents, 'pages': pages}

    try:
        with schema_context(schema):
            documents = _load_delivery_note_documents(shipment, limit=limit)
    except ProgrammingError as exc:
        logger.warning(
            'hard_pod_confirmation_pages schema=%s shipment=%s err=%s',
            schema,
            getattr(shipment, 'pk', None),
            exc,
        )
        documents = [_synthetic_document_from_shipment(shipment, limit=limit)]
    pages = _flatten_pages(documents)
    return {'documents': documents, 'pages': pages}


def build_hard_pod_confirmation_pages(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Flat page rows (legacy / checklist consumers)."""
    return build_hard_pod_confirmation_context(
        shipment,
        tenant_schema=tenant_schema,
        limit=limit,
    ).get('pages', [])


def _flatten_pages(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for document in documents:
        document_id = (document.get('document_id') or '').strip()
        for page in list(document.get('pages') or []):
            row = dict(page)
            row['document_id'] = document_id
            rows.append(row)
    return rows


def _load_delivery_note_documents(
    shipment: Any,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    from tenant_workspace.models import TenantShipmentDocument

    documents = list(
        TenantShipmentDocument.objects.filter(
            shipment_id=getattr(shipment, 'pk', None),
            is_delivery_note=True,
        )
        .prefetch_related('document_pages', 'pod_pages')
        .order_by('-updated_at', '-created_at')[:10]
    )
    if not documents:
        return [_synthetic_document_from_shipment(shipment, limit=limit)]

    rows: list[dict[str, Any]] = []
    for document in documents:
        rows.append(_document_row_from_shipment_document(document, limit=limit))
    return rows


def _document_row_from_shipment_document(
    document: Any,
    *,
    limit: int,
) -> dict[str, Any]:
    doc_pages = list(document.document_pages.order_by('line_no', 'created_at')[:limit])
    if doc_pages:
        pages = [_page_row_from_document_page(line, document=document) for line in doc_pages]
    else:
        pod_pages = list(document.pod_pages.order_by('line_no', 'created_at')[:limit])
        pages = [_page_row_from_pod_page(line, document=document) for line in pod_pages]

    return {
        'document_id': str(getattr(document, 'pk', '') or ''),
        'record_no': (getattr(document, 'record_no', None) or '').strip(),
        'document_type': (getattr(document, 'document_type', None) or '').strip(),
        'document_ref_no': (getattr(document, 'document_ref_no', None) or '').strip(),
        'document_date': _iso_date(getattr(document, 'document_date', None)),
        'is_delivery_note': bool(getattr(document, 'is_delivery_note', False)),
        'page_count': int(getattr(document, 'page_count', None) or len(pages) or 0),
        'status': (getattr(document, 'status', None) or '').strip(),
        'physical_location': (getattr(document, 'physical_location', None) or '').strip(),
        'pages': pages,
    }


def _synthetic_document_from_shipment(
    shipment: Any,
    *,
    limit: int,
) -> dict[str, Any]:
    """Fallback when OP-DOC pages are not configured yet."""
    pages = _synthetic_pages_from_shipment(shipment, limit=limit)
    shipment_no = (getattr(shipment, 'shipment_no', None) or 'DOC').strip()
    return {
        'document_id': '',
        'record_no': '',
        'document_type': 'Delivery Note',
        'document_ref_no': shipment_no,
        'document_date': '',
        'is_delivery_note': True,
        'page_count': len(pages),
        'status': '',
        'physical_location': '',
        'pages': pages,
    }


def _synthetic_pages_from_shipment(
    shipment: Any,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    page_count = int(getattr(shipment, 'pod_doc_count', None) or 0)
    if page_count <= 0:
        page_count = 1
    page_count = min(page_count, limit)
    rows: list[dict[str, Any]] = []
    shipment_no = (getattr(shipment, 'shipment_no', None) or 'DOC').strip()
    for line_no in range(1, page_count + 1):
        label = f'IMG-({shipment_no}-{line_no:03d})'
        rows.append(
            {
                'page_id': '',
                'line_no': line_no,
                'label': label,
                'physical_page_no': line_no,
                'confirmation_text': (
                    f'I confirm the physical receipt of this original document of {line_no}'
                ),
                'attachment_label': '',
                'signer_location': '',
                'completion_status': '',
            }
        )
    return rows


def _page_row_from_document_page(line: Any, *, document: Any | None = None) -> dict[str, Any]:
    ref = (getattr(line, 'doc_ref_no', None) or '').strip()
    page_no = int(getattr(line, 'physical_page_no', None) or 0) or int(
        getattr(line, 'line_no', None) or 1
    )
    if not ref and document is not None:
        doc_ref = (getattr(document, 'document_ref_no', None) or '').strip()
        ref = f'{doc_ref}-P{page_no}' if doc_ref else f'Page-{page_no}'
    label = ref or f'Page-{page_no}'
    return {
        'page_id': str(getattr(line, 'pk', '') or ''),
        'line_no': int(getattr(line, 'line_no', None) or 0),
        'label': label,
        'physical_page_no': page_no,
        'confirmation_text': (
            f'I confirm the physical receipt of this original document of {page_no}'
        ),
        'attachment_label': (getattr(line, 'attachment_label', None) or '').strip(),
        'signer_location': (getattr(line, 'signer_location', None) or '').strip(),
        'completion_status': (getattr(line, 'completion_status', None) or '').strip(),
    }


def _page_row_from_pod_page(line: Any, *, document: Any | None = None) -> dict[str, Any]:
    page_token = (getattr(line, 'doc_page', None) or '').strip()
    line_no = int(getattr(line, 'line_no', None) or 1)
    page_no = int(page_token) if page_token.isdigit() else line_no
    label = (getattr(line, 'source', None) or '').strip()
    if not label and document is not None:
        doc_ref = (getattr(document, 'document_ref_no', None) or '').strip()
        label = f'{doc_ref}-P{page_no}' if doc_ref else f'Page-{page_no}'
    label = label or f'Page-{page_no}'
    return {
        'page_id': str(getattr(line, 'pk', '') or ''),
        'line_no': line_no,
        'label': label,
        'physical_page_no': page_no,
        'confirmation_text': (
            f'I confirm the physical receipt of this original document of {page_no}'
        ),
        'attachment_label': (getattr(line, 'attachment_label', None) or '').strip(),
        'signer_location': (getattr(line, 'physical_location', None) or '').strip(),
        'completion_status': (getattr(line, 'soft_copy_status', None) or '').strip(),
    }


def _iso_date(value: Any) -> str:
    if value is None:
        return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value).strip()
