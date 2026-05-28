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
        file_key = f"{prefix}[{index}][file_ref]"
        if file_key not in request_files:
            break
        uploaded_file = request_files[file_key]

        if not validate_file_type(uploaded_file):
            raise ValueError(
                f"File type {uploaded_file.content_type} not allowed. "
                "Allowed: image/jpeg, image/png, image/webp, video/mp4"
            )
        if not validate_file_size(uploaded_file):
            raise ValueError("File size exceeds 50MB limit.")

        saved_path = save_uploaded_file(uploaded_file, subfolder=subfolder)

        item = {
            'file_ref': saved_path,
            'file_name': request_data.get(
                f"{prefix}[{index}][file_name]",
                uploaded_file.name,
            ),
            'media_type': request_data.get(
                f"{prefix}[{index}][media_type]",
                'photo',
            ),
            'description': request_data.get(
                f"{prefix}[{index}][description]",
                '',
            ),
            'sort_order': int(
                request_data.get(
                    f"{prefix}[{index}][sort_order]",
                    index,
                )
            ),
        }
        processed.append(item)
        index += 1

    return processed
