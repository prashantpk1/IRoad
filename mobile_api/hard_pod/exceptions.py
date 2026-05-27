"""
mobile_api/hard_pod/exceptions.py

Domain errors for Hard POD custody submit (view HTTP mapping).
"""
from __future__ import annotations


class HardPodError(Exception):
    """Hard POD failure with HTTP mapping for the view layer."""

    def __init__(
        self,
        message: str,
        *,
        code: str = 'hard_pod_error',
        http_status: int = 400,
        message_key: str = 'mobile.validation.failed',
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message_key = message_key
