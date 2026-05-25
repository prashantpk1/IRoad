"""
Persist operation action log media from mobile multipart / JSON payloads.
"""

from __future__ import annotations

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tenant_workspace.models import TenantOperationActionMedia


def _is_coordinate(value) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False


def normalize_location_fields(
    *,
    latitude: str = '',
    longitude: str = '',
    map_link: str = '',
) -> dict[str, str]:
    lat = (latitude or '').strip()
    lng = (longitude or '').strip()
    link = (map_link or '').strip()
    if _is_coordinate(lat) and _is_coordinate(lng) and not link.lower().startswith(
        ('http://', 'https://')
    ):
        link = f'https://maps.google.com/?q={lat},{lng}'
    if not _is_coordinate(lat):
        lat = ''
    if not _is_coordinate(lng):
        lng = ''
    return {'latitude': lat, 'longitude': lng, 'map_link': link[:500]}


def _media_items_from_request(request) -> list[dict]:
    """JSON ``media`` array and/or indexed multipart fields."""
    items: list[dict] = []
    data = getattr(request, 'data', None) or {}
    if hasattr(data, 'get'):
        raw = data.get('media')
        if isinstance(raw, list):
            for row in raw:
                if isinstance(row, dict):
                    items.append(row)

    if request is None:
        return items

    types = _post_list(request, 'media_type') or _post_list(request, 'oal_media_type')
    descriptions = _post_list(request, 'media_description') or _post_list(
        request, 'oal_media_description'
    )
    captured_list = _post_list(request, 'media_captured_at') or _post_list(
        request, 'oal_media_captured_at'
    )
    uploads = []
    if hasattr(request, 'FILES'):
        uploads = (
            request.FILES.getlist('media_file')
            or request.FILES.getlist('media_file[]')
            or request.FILES.getlist('oal_media_file')
            or request.FILES.getlist('oal_media_file[]')
        )

    max_len = max(len(types), len(descriptions), len(captured_list), len(uploads), 0)
    for idx in range(max_len):
        upload = uploads[idx] if idx < len(uploads) else None
        media_type = (types[idx] if idx < len(types) else '').strip()
        description = (descriptions[idx] if idx < len(descriptions) else '').strip()
        captured_raw = (captured_list[idx] if idx < len(captured_list) else '').strip()
        if not any([media_type, description, captured_raw, upload]):
            continue
        items.append(
            {
                'media_type': media_type,
                'description': description,
                'captured_at': captured_raw,
                'file': upload,
            }
        )
    return items


def _post_list(request, base_name: str) -> list[str]:
    if request is None or not hasattr(request, 'POST'):
        return []
    values = request.POST.getlist(f'{base_name}[]')
    if not values:
        values = request.POST.getlist(base_name)
    return values


def count_media_attachments(request) -> int:
    return len(_media_items_from_request(request))


def save_action_log_media_from_mobile_request(action_log, request) -> int:
    """
    Append media rows for a new action log. Returns number of rows saved.
    Skipped when ``reused_existing`` log should not gain duplicate media (caller duty).
    """
    items = _media_items_from_request(request)
    if not items:
        return 0

    line_no = (
        action_log.media_rows.order_by('-line_no').values_list('line_no', flat=True).first()
        or 0
    )
    saved = 0
    for row in items:
        media_type = (row.get('media_type') or '').strip()
        description = (row.get('description') or '').strip()
        captured_raw = (row.get('captured_at') or '').strip()
        upload = row.get('file')
        if not any([media_type, description, captured_raw, upload]):
            continue
        line_no += 1
        captured_at = None
        if captured_raw:
            captured_at = parse_datetime(captured_raw)
            if captured_at is not None and timezone.is_naive(captured_at):
                captured_at = timezone.make_aware(
                    captured_at,
                    timezone.get_current_timezone(),
                )
        TenantOperationActionMedia.objects.create(
            action_log=action_log,
            line_no=line_no,
            media_type=media_type[:16],
            description=description[:255],
            captured_at=captured_at,
            file=upload,
        )
        saved += 1
    return saved
