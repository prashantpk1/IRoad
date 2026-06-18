"""Pure helpers for POD action-log map URL and attachment metadata (PCS §5.6.2)."""
from __future__ import annotations


def action_log_map_url(log) -> str:
    """Build Google Maps URL from action log coords or stored map_link."""
    if log is None:
        return ''
    map_link = (getattr(log, 'map_link', '') or '').strip()
    if map_link.lower().startswith(('http://', 'https://')):
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
