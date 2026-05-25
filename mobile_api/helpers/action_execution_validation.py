"""
Mobile execute-action validation against Action Master metadata projections.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from iroad_tenants.operation_execution import action_matches
from mobile_api.helpers.action_execution_metadata import build_execution_requirements
from mobile_api.helpers.action_log_media import count_media_attachments


def _parse_cod_amount(raw) -> Decimal | None:
    if raw is None or raw == '':
        return None
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(_('mobile.jobs.execute.invalid_cod_amount'))
    if value <= 0:
        raise ValidationError(_('mobile.jobs.execute.cod_amount_required'))
    return value


def validate_mobile_execution_payload(
    *,
    operation_action,
    request,
    shipment=None,
    requirements: dict | None = None,
) -> dict:
    """
    Validate GPS / media / notes for driver execute. Returns normalized location + cod.
    """
    if operation_action is None:
        raise ValidationError(_('mobile.jobs.execute.invalid_action'))

    req = requirements or build_execution_requirements(operation_action)
    data = getattr(request, 'data', None) or {}

    def _get(key: str, default='') -> str:
        if hasattr(data, 'get'):
            return str(data.get(key, default) or '').strip()
        return default

    notes = _get('notes')
    latitude = _get('latitude')
    longitude = _get('longitude')
    map_link = _get('map_link')

    if req.get('gps'):
        if not latitude or not longitude:
            raise ValidationError(_('mobile.jobs.execute.gps_required'))

    if req.get('note') or req.get('note_required'):
        if req.get('note_required') and not notes:
            raise ValidationError(_('mobile.jobs.execute.note_required'))

    photo_min = int(req.get('photo_min_count') or 0)
    if req.get('photo') and photo_min > 0:
        media_count = count_media_attachments(request)
        if media_count < photo_min:
            raise ValidationError(_('mobile.jobs.execute.photo_required'))

    if req.get('video') and int(req.get('video_min_count') or 0) > 0:
        media_count = count_media_attachments(request)
        if media_count < 1:
            raise ValidationError(_('mobile.jobs.execute.video_required'))

    cod_amount = None
    if shipment is not None and action_matches(
        operation_action,
        'collect payment',
        'a9',
        'action 9',
    ):
        cod_amount = _parse_cod_amount(_get('cod_amount') or shipment.cod_amount)

    from mobile_api.helpers.action_log_media import normalize_location_fields

    location = normalize_location_fields(
        latitude=latitude,
        longitude=longitude,
        map_link=map_link,
    )
    return {
        'notes': notes,
        'latitude': location['latitude'],
        'longitude': location['longitude'],
        'map_link': location['map_link'],
        'cod_amount': cod_amount,
    }
