"""Pure helpers for POD action-log map URL and attachment metadata (PCS §5.6.2)."""
from __future__ import annotations

from typing import Any, Callable


def is_http_url(value: str) -> bool:
    return (value or '').strip().lower().startswith(('http://', 'https://'))


def action_log_map_url(log) -> str:
    """Build Google Maps URL from action log coords or stored map_link."""
    if log is None:
        return ''
    map_link = (getattr(log, 'map_link', '') or '').strip()
    if is_http_url(map_link):
        return map_link
    latitude = (getattr(log, 'latitude', '') or '').strip()
    longitude = (getattr(log, 'longitude', '') or '').strip()
    if latitude and longitude:
        try:
            float(latitude)
            float(longitude)
            return f'https://maps.google.com/?q={latitude},{longitude}'
        except ValueError:
            return ''
    return ''


def action_log_attachment_meta_from_media(media_rows) -> tuple[str, str]:
    """Return (label, url) for the first media evidence row."""
    if not media_rows:
        return '', ''
    media = list(media_rows)[:1][0]
    label = (getattr(media, 'description', '') or '').strip()
    file_obj = getattr(media, 'file', None)
    file_name = ''
    if file_obj:
        file_name = file_obj.name.rsplit('/', 1)[-1]
    if not label:
        label = file_name or 'Attachment'
    url = ''
    if file_obj:
        try:
            url = file_obj.url
        except Exception:
            url = file_obj.name or ''
    return label, url


def action_log_attachment_storage_path_from_media(media_rows) -> str:
    """Return storage path for the first media evidence row."""
    if not media_rows:
        return ''
    media = list(media_rows)[:1][0]
    file_obj = getattr(media, 'file', None)
    if not file_obj:
        return ''
    return (getattr(file_obj, 'name', '') or '').strip()


def legacy_attachment_storage_path_from_map_url(map_url: str) -> str:
    """Before attachment_storage_path existed, file paths were stored in map_url."""
    raw = (map_url or '').strip()
    if not raw or is_http_url(raw):
        return ''
    return raw


def resolve_pod_page_display_row(
    line: Any,
    *,
    file_url_builder: Callable[[str], str] | None = None,
    attachment_meta_resolver: Callable[[Any], tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Normalize a TenantShipmentPodPage (or compatible object) for UI display.

    Separates Google Maps links from attachment storage paths and falls back to
    linked action-log evidence when line fields are empty or legacy-misstored.
    """
    build_url = file_url_builder or (lambda _path: '')
    resolve_attachment = attachment_meta_resolver or (lambda _log: ('', ''))

    stored_map = (getattr(line, 'map_url', '') or '').strip()
    storage_path = (getattr(line, 'attachment_storage_path', '') or '').strip()
    if not storage_path:
        storage_path = legacy_attachment_storage_path_from_map_url(stored_map)

    map_url = stored_map if is_http_url(stored_map) else ''
    action_log = getattr(line, 'action_log', None)
    if not map_url:
        map_url = action_log_map_url(action_log)

    attachment_label = (getattr(line, 'attachment_label', '') or '').strip()
    attachment_url = build_url(storage_path) if storage_path else ''

    if not attachment_url:
        meta_label, meta_url = resolve_attachment(action_log)
        if not attachment_label:
            attachment_label = meta_label
        attachment_url = meta_url

    return {
        'line_no': getattr(line, 'line_no', 0),
        'doc_page': getattr(line, 'doc_page', '') or '',
        'source': getattr(line, 'source', '') or '',
        'action_log': action_log,
        'map_url': map_url,
        'attachment_label': attachment_label,
        'attachment_url': attachment_url,
        'attachment_storage_path': storage_path,
    }
