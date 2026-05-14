"""
mobile_api/serializers/localized.py

Global standard — multilingual **response** fields for the mobile API
-----------------------------------------------------------------------

1. **Single JSON key per concept** — never return parallel ``*_en`` / ``*_ar``,
   ``english_*`` / ``arabic_*`` pairs in API payloads. Use one field (e.g.
   ``name``, ``label``, or ``serialize_localized_field(..., field_name='title')``).

2. **Language** — resolve from ``Accept-Language`` on ``request`` only (see
   ``mobile_api.helpers.i18n.get_request_language``). Missing / unsupported
   → English (``en``).

3. **Fallback** — ``get_localized_value``: prefer chosen language; if that
   side is empty, use the other language so responses stay usable.

4. **Implementation** — pass ``serializer.context['request']`` into the module
   helpers below, or subclass ``LocalizedSerializerMixin`` and call instance
   methods. Do not branch on ``translation.get_language()`` for payload text.

5. **Models / DB** — keep existing ``english_name``, ``arabic_label``, etc. on
   models; only serialized output changes.

Reusable helpers
----------------
``serialize_localized_name`` / ``serialize_localized_label`` /
``serialize_localized_field`` build one-key dicts for nesting into
``data`` envelopes.
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.i18n import get_localized_value


def serialize_localized_field(
    request,
    english_value: Any,
    arabic_value: Any,
    *,
    field_name: str,
) -> dict[str, str]:
    """
    Single-key dict for an arbitrary JSON field name (master / generic use).

    Example: ``field_name='title'`` → ``{"title": "..."}``.
    """
    return {
        field_name: get_localized_value(request, english_value, arabic_value),
    }


def serialize_localized_name(
    request,
    english_value: Any,
    arabic_value: Any,
) -> dict[str, str]:
    """``{"name": "<localized>"}`` — person / entity display names."""
    return serialize_localized_field(
        request,
        english_value,
        arabic_value,
        field_name='name',
    )


def serialize_localized_label(
    request,
    english_value: Any,
    arabic_value: Any,
) -> dict[str, str]:
    """``{"label": "<localized>"}`` — master data labels (e.g. truck type)."""
    return serialize_localized_field(
        request,
        english_value,
        arabic_value,
        field_name='label',
    )


class LocalizedSerializerMixin:
    """
    Mixin for DRF serializers with ``context={'request': request}``.

    Delegates to module-level helpers using ``self.context.get('request')``.
    """

    def _localized_request(self):
        return self.context.get('request')

    def serialize_localized_field(
        self,
        english_value: Any,
        arabic_value: Any,
        *,
        field_name: str,
    ) -> dict[str, str]:
        return serialize_localized_field(
            self._localized_request(),
            english_value,
            arabic_value,
            field_name=field_name,
        )

    def serialize_localized_name(
        self,
        english_value: Any,
        arabic_value: Any,
    ) -> dict[str, str]:
        return serialize_localized_name(
            self._localized_request(),
            english_value,
            arabic_value,
        )

    def serialize_localized_label(
        self,
        english_value: Any,
        arabic_value: Any,
    ) -> dict[str, str]:
        return serialize_localized_label(
            self._localized_request(),
            english_value,
            arabic_value,
        )
