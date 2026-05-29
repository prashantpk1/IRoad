"""
mobile_api/history/exceptions.py
"""
from __future__ import annotations


class HistoryError(Exception):
    """Domain error for History APIs."""

    def __init__(
        self,
        message: str,
        *,
        code: str = 'history_error',
        http_status: int = 400,
        message_key: str = 'mobile.history.error',
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message_key = message_key
