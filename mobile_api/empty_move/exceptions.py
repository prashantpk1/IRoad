"""Empty move mobile API errors."""
from __future__ import annotations


class EmptyMoveError(Exception):
    """Empty move creation failure with HTTP mapping for the view layer."""

    def __init__(
        self,
        message: str,
        *,
        code: str = 'empty_move_error',
        http_status: int = 400,
        message_key: str = 'mobile.validation.failed',
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message_key = message_key
