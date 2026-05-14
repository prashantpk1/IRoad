"""
mobile_api/serializers/driver_organization_profile.py

Read-only serializer for tenant ``OrganizationProfile`` on the mobile driver API.
See ``mobile_api/docs/driver_organization_profile.md`` for endpoint usage notes.

Localization (``organization_name``)
--------------------------------------
Uses ``serialize_localized_field`` → ``get_localized_value`` →
``get_request_language(request)``, which reads **only** the ``Accept-Language``
header (first tag, two-letter code). Supported: ``en``, ``ar``; anything else
or missing header → **English** selection rules (prefer ``name_en``, fall back
to ``name_ar`` if English empty).

This is the same bilingual pattern as other mobile serializers; it does **not**
rely on Django's active translation language for picking ``name_en`` vs ``name_ar``.

Driver instructions (single DB column)
----------------------------------------
``driver_instructions`` is one ``TextField`` on the model. There are **no**
``_en`` / ``_ar`` columns. The API returns **the same string for every**
``Accept-Language`` value (trimmed); clients may render HTML if stored from CMS.

Null / missing values
---------------------
All response values are strings. Absent text → ``''``. Absent logo → ``logo_url``
is ``''`` (never omitted). ``instance`` may be ``None`` → all-empty dict without
raising.
"""
from __future__ import annotations

from typing import Any

from rest_framework import serializers

from mobile_api.serializers.driver_profile import safe_media_url
from mobile_api.serializers.localized import (
    LocalizedSerializerMixin,
    serialize_localized_field,
)


def _str_or_empty(value: Any) -> str:
    """Coerce model / None values to a safe trimmed string for JSON."""
    if value is None:
        return ''
    s = str(value).strip()
    return s


class DriverOrganizationProfileSerializer(LocalizedSerializerMixin, serializers.Serializer):
    """
    Flat organization/support snapshot for mobile clients.

    Pass ``instance`` as an ``OrganizationProfile`` model instance (or ``None``).
    Requires ``context={'request': request}`` for ``Accept-Language`` on
    ``organization_name`` and for absolute ``logo_url`` resolution.
    """

    def to_representation(self, instance: Any) -> dict[str, str]:
        request = self.context.get('request')
        empty = {
            'organization_name': '',
            'support_email': '',
            'support_mobile_number_1': '',
            'support_mobile_number_2': '',
            'driver_instructions': '',
            'logo_url': '',
        }
        if instance is None:
            return empty

        name_part = serialize_localized_field(
            request,
            getattr(instance, 'name_en', None),
            getattr(instance, 'name_ar', None),
            field_name='organization_name',
        )
        logo = safe_media_url(request, getattr(instance, 'logo_file', None))

        return {
            **name_part,
            'support_email': _str_or_empty(getattr(instance, 'support_email', None)),
            'support_mobile_number_1': _str_or_empty(
                getattr(instance, 'support_mobile_1', None)
            ),
            'support_mobile_number_2': _str_or_empty(
                getattr(instance, 'support_mobile_2', None)
            ),
            # Single DB field: identical for all Accept-Language values.
            'driver_instructions': _str_or_empty(
                getattr(instance, 'driver_instructions', None)
            ),
            'logo_url': _str_or_empty(logo),
        }
