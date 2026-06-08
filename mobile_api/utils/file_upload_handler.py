import os
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

ALLOWED_IMAGE_TYPES = [
    'image/jpeg', 
    'image/png', 
    'image/jpg', 
    'image/webp', 
    'image/heic', 
    'image/heif', 
    'image/gif', 
    'image/bmp', 
    'image/x-adobe-dng', 
    'image/tiff'
]

ALLOWED_VIDEO_TYPES = [
    'video/mp4', 
    'video/quicktime', 
    'video/x-msvideo', 
    'video/mpeg', 
    'video/webm', 
    'video/3gpp', 
    'video/3gpp2', 
    'video/mp2t', 
    'video/hevc', 
    'video/x-matroska'
]

ALLOWED_TYPES = ALLOWED_IMAGE_TYPES + ALLOWED_VIDEO_TYPES
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB

VIDEO_EXTENSIONS = frozenset(
    {'.mp4', '.mov', '.webm', '.avi', '.mpeg', '.mpg', '.3gp', '.mkv', '.m4v'}
)
PHOTO_EXTENSIONS = frozenset(
    {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.gif', '.bmp', '.tif', '.tiff'}
)
_MEDIA_FILE_FIELDS = ('file_ref', 'file', 'upload', 'media')


def _form_field_value(request_data, key: str, default: str = '') -> str:
    """Normalize QueryDict values (single str or one-element list)."""
    if request_data is None:
        return default
    getter = getattr(request_data, 'get', None)
    if getter is None:
        return default
    value = getter(key, default)
    if isinstance(value, (list, tuple)):
        return str(value[0]).strip() if value else default
    return str(value or default).strip() or default


def infer_media_type(
    *,
    explicit: str = '',
    content_type: str = '',
    file_name: str = '',
    file_ref: str = '',
) -> str:
    """
    Resolve mobile ``media_type`` when clients omit it on multipart uploads.

    Defaults used to be always ``photo``, which caused ``video_required`` even
    when a video file was uploaded.
    """
    token = (explicit or '').strip().casefold()
    if token in {'photo', 'video', 'document', 'signature'}:
        return token

    content = (content_type or '').strip().casefold()
    if content.startswith('video/'):
        return 'video'
    if content.startswith('image/'):
        return 'photo'

    for candidate in (file_name, file_ref):
        _, ext = os.path.splitext((candidate or '').strip().lower())
        if ext in VIDEO_EXTENSIONS:
            return 'video'
        if ext in PHOTO_EXTENSIONS:
            return 'photo'

    _, ext = os.path.splitext((file_ref or file_name or '').strip().lower())
    if ext in VIDEO_EXTENSIONS:
        return 'video'
    if ext in PHOTO_EXTENSIONS:
        return 'photo'
    return 'photo'


def _resolve_multipart_upload(request_files, *, prefix: str, index: int):
    for field in _MEDIA_FILE_FIELDS:
        key = f'{prefix}[{index}][{field}]'
        if key in request_files:
            return request_files[key]
    return None


def save_uploaded_file(uploaded_file, subfolder='uploads'):
    """
    Save an uploaded file from request.FILES to MEDIA_ROOT.
    Returns the relative file path string to store as file_ref.
    """
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    relative_path = f"mobile/{subfolder}/{unique_name}"
    saved_path = default_storage.save(
        relative_path,
        ContentFile(uploaded_file.read()),
    )
    return saved_path


def validate_file_type(uploaded_file):
    """
    Returns True if file content_type is allowed.
    """
    return uploaded_file.content_type in ALLOWED_TYPES


def validate_file_size(uploaded_file):
    """
    Returns True if file size is within limit.
    """
    return uploaded_file.size <= MAX_FILE_SIZE_BYTES


def process_media_files(
    request_files,
    request_data,
    *,
    prefix='media',
    subfolder='evidence',
):
    """
    Process request.FILES for media uploads.

    Accepts files posted as:
      media[0][file_ref] = <file>
      media[1][file_ref] = <file>

    Returns list of media dicts with file_ref replaced
    by saved file path.

    Also accepts plain JSON media array unchanged
    (for clients that send pre-uploaded URLs).
    """
    processed = []
    index = 0
    while True:
        uploaded_file = _resolve_multipart_upload(request_files, prefix=prefix, index=index)
        if uploaded_file is None:
            break

        if not validate_file_type(uploaded_file):
            raise ValueError(
                f"File type {uploaded_file.content_type} not allowed. "
                "Allowed: image/jpeg, image/png, image/webp, video/mp4"
            )
        if not validate_file_size(uploaded_file):
            raise ValueError("File size exceeds 50MB limit.")

        saved_path = save_uploaded_file(uploaded_file, subfolder=subfolder)
        explicit_type = _form_field_value(
            request_data,
            f'{prefix}[{index}][media_type]',
        )

        item = {
            'file_ref': saved_path,
            'file_name': _form_field_value(
                request_data,
                f'{prefix}[{index}][file_name]',
                uploaded_file.name,
            ),
            'media_type': infer_media_type(
                explicit=explicit_type,
                content_type=str(getattr(uploaded_file, 'content_type', '') or ''),
                file_name=str(getattr(uploaded_file, 'name', '') or ''),
                file_ref=saved_path,
            ),
            'description': _form_field_value(
                request_data,
                f'{prefix}[{index}][description]',
            ),
            'sort_order': int(
                _form_field_value(
                    request_data,
                    f'{prefix}[{index}][sort_order]',
                    str(index),
                )
                or index
            ),
        }
        processed.append(item)
        index += 1

    return processed


def merge_multipart_media_with_json_hints(
    request,
    *,
    prefix: str = 'media',
    subfolder: str = 'evidence',
) -> list[dict] | None:
    """
    Build ``media[]`` for serializers from multipart + optional JSON metadata.

    Preserves ``media_type`` from a JSON ``media`` array when the client sends
    both bracketed files and typed rows in the body.
    """
    import json

    request_files = getattr(request, 'FILES', None) or {}
    request_data = getattr(request, 'data', None) or {}
    if not any(str(k).startswith(f'{prefix}[') for k in request_files.keys()):
        return None

    processed = process_media_files(
        request_files,
        request_data,
        prefix=prefix,
        subfolder=subfolder,
    )
    if not processed:
        return None

    raw_media = request_data.get(prefix)
    json_rows: list[dict] = []
    if isinstance(raw_media, list):
        json_rows = [row for row in raw_media if isinstance(row, dict)]
    elif isinstance(raw_media, str) and raw_media.strip().startswith('['):
        try:
            parsed = json.loads(raw_media)
            if isinstance(parsed, list):
                json_rows = [row for row in parsed if isinstance(row, dict)]
        except json.JSONDecodeError:
            json_rows = []

    for index, item in enumerate(processed):
        if index < len(json_rows):
            explicit = str(json_rows[index].get('media_type') or '').strip()
            if explicit:
                item['media_type'] = infer_media_type(
                    explicit=explicit,
                    file_ref=item.get('file_ref', ''),
                    file_name=item.get('file_name', ''),
                )
    return processed
