"""
mobile_api/response_envelope.py

Unified JSON contract for **all** Mobile API responses (auth, profile, lists).

Envelope shape::

    {
      "status": 1 | 0 | 2,
      "message": "<human-readable, Accept-Language resolved>",
      "message_key": "<optional gettext msgid for client-side i18n>",
      "data": { ... },
      "meta": {
        "request_id": "<uuid or client X-Request-ID>",
        "timestamp": "<ISO-8601 UTC>",
        "locale": "<active language code>",
        "api_version": "<contract string>"
      }
    }

- ``status`` **1** = success, **0** = client/business error, **2** = auth/session error.
- Business errors include ``data.error`` = ``{ "code", "details" }`` plus optional
  ``data.validation`` for serializer failures.
- ``message_key`` is omitted when unknown (dynamic server messages).

See ``mobile_api/docs/API_RESPONSE_CONTRACT.md``.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('mobile_api')


def mobile_auth_error_message_key(code: str) -> str | None:
    """
    Map ``error_code`` values from auth/profile services to gettext msgids.

    Used for the optional ``message_key`` field on API envelopes.
    """
    if not code:
        return None
    overrides = {
        'server_error': 'mobile.error.server_error',
        'otp_verify_failed': 'mobile.auth.otp_verify_failed',
        'reset_password_failed': 'mobile.auth.reset_password_failed',
        'tenant_ambiguous_operation': 'mobile.auth.tenant_ambiguous_operation',
        'auth_failed': 'mobile.auth.invalid_credentials',
    }
    if code in overrides:
        return overrides[code]
    return f'mobile.auth.{code}'


def ensure_mobile_request_id(request: Any) -> str:
    """
    Attach a stable id to ``request`` for tracing (header or generated).

    Honors ``X-Request-ID`` / ``X-Correlation-ID`` when present (trimmed, max 64).
    """
    if request is None:
        return str(uuid.uuid4())
    existing = getattr(request, 'mobile_request_id', None)
    if existing:
        return str(existing)
    for header in ('HTTP_X_REQUEST_ID', 'HTTP_X_CORRELATION_ID'):
        raw = (request.META.get(header) or '').strip()
        if raw:
            rid = raw[:64]
            setattr(request, 'mobile_request_id', rid)
            return rid
    rid = str(uuid.uuid4())
    setattr(request, 'mobile_request_id', rid)
    return rid


def build_meta(request: Any | None, **extra: Any) -> dict[str, Any]:
    """Standard ``meta`` block for every Mobile API response."""
    try:
        from mobile_api.helpers.i18n import get_request_language

        loc = get_request_language(request) if request is not None else ''
    except Exception:
        loc = ''
    rid = ensure_mobile_request_id(request) if request is not None else str(uuid.uuid4())
    meta: dict[str, Any] = {
        'request_id': rid,
        'timestamp': timezone.now().isoformat().replace('+00:00', 'Z'),
        'locale': loc or '',
        'api_version': (
            getattr(settings, 'MOBILE_API_CONTRACT_VERSION', None) or '1.0'
        ),
    }
    for k, v in extra.items():
        if v is not None:
            meta[k] = v
    return meta


def _coerce_detail_item(item: Any) -> dict[str, str]:
    """Single DRF ErrorDetail (or primitive) → {message, code}."""
    code = 'invalid'
    msg = str(item)
    try:
        if hasattr(item, 'code') and item.code is not None:
            code = str(item.code)
    except Exception:
        pass
    try:
        if hasattr(item, 'string'):
            msg = str(item.string)
    except Exception:
        pass
    return {'message': msg, 'code': code}


def drf_errors_to_validation_fields(detail: Any) -> dict[str, list[dict[str, str]]]:
    """
    Normalize DRF ``serializer.errors`` / ``ValidationError.detail`` into::

        { "field": [ {"message": "...", "code": "..."}, ... ], ... }
    """
    out: dict[str, list[dict[str, str]]] = {}

    if isinstance(detail, list):
        out['non_field_errors'] = [_coerce_detail_item(x) for x in detail]
        return out
    if not isinstance(detail, dict):
        out['non_field_errors'] = [_coerce_detail_item(detail)]
        return out

    for key, value in detail.items():
        if isinstance(value, list):
            row: list[dict[str, str]] = []
            for item in value:
                if isinstance(item, dict):
                    inner = drf_errors_to_validation_fields(item)
                    for sub_key, sub_list in inner.items():
                        fk = f'{key}.{sub_key}' if sub_key != 'non_field_errors' else key
                        out[fk] = sub_list
                else:
                    row.append(_coerce_detail_item(item))
            if row:
                out[str(key)] = row
        elif isinstance(value, dict):
            inner = drf_errors_to_validation_fields(value)
            for sub_key, sub_list in inner.items():
                out[f'{key}.{sub_key}'] = sub_list
        else:
            out[str(key)] = [_coerce_detail_item(value)]
    return out


def validation_flat_first_messages(
    fields: dict[str, list[dict[str, str]]],
) -> dict[str, str]:
    """One string per field for legacy ``data.errors`` flat map."""
    flat: dict[str, str] = {}
    for field, msgs in fields.items():
        if not msgs:
            continue
        flat[field] = msgs[0].get('message', '')
    return flat


def merge_error_into_data(
    base: dict[str, Any] | None,
    *,
    code: str,
    details: dict[str, Any] | None,
    validation_fields: dict[str, list[dict[str, str]]] | None,
) -> dict[str, Any]:
    """
    Build canonical ``data`` for error responses.

    - ``data.error`` — machine code + optional details (candidates, etc.).
    - ``data.validation`` — present only for serializer validation failures.
    - ``data.error_code`` — duplicate of ``data.error.code`` (legacy clients).
    - ``data.errors`` — flat field → first message (legacy clients).
    """
    data: dict[str, Any] = dict(base) if base else {}
    # Drop legacy-only keys we will replace structurally
    for k in ('error_code', 'errors', 'error', 'validation'):
        data.pop(k, None)

    det = dict(details or {})
    data['error'] = {'code': code, 'details': det}
    data['error_code'] = code

    if validation_fields:
        flat = validation_flat_first_messages(validation_fields)
        data['validation'] = {'fields': validation_fields}
        data['errors'] = flat
    return data


def build_success_body(
    *,
    message: str,
    data: dict[str, Any] | None,
    request: Any | None,
    message_key: str | None = None,
    meta_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        'status': 1,
        'message': message,
        'data': data if data is not None else {},
        'meta': build_meta(request, **(meta_extra or {})),
    }
    if message_key:
        body['message_key'] = message_key
    return body


def build_error_body(
    *,
    app_status: int,
    message: str,
    request: Any | None,
    code: str,
    message_key: str | None = None,
    data: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    validation_fields: dict[str, list[dict[str, str]]] | None = None,
    meta_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = merge_error_into_data(
        data,
        code=code,
        details=details,
        validation_fields=validation_fields,
    )
    body: dict[str, Any] = {
        'status': app_status,
        'message': message,
        'data': merged,
        'meta': build_meta(request, **(meta_extra or {})),
    }
    if message_key:
        body['message_key'] = message_key
    return body


def validation_error_body_from_drf(
    *,
    message: str,
    request: Any | None,
    drf_detail: Any,
    message_key: str = 'mobile.validation.failed',
    meta_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """DRF validation ``detail`` → full envelope (``status`` 0)."""
    fields = drf_errors_to_validation_fields(drf_detail)
    return build_error_body(
        app_status=0,
        message=message,
        request=request,
        code='validation_failed',
        message_key=message_key,
        details={},
        validation_fields=fields,
        meta_extra=meta_extra,
    )