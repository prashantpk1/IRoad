"""
mobile_api/job_detail/timeline/timeline_cursor_service.py

Keyset cursor encode/decode for Job Detail timeline pagination.

Delegates token format to ``iroad_tenants.operation_runtime.timeline_cursor``.
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.timeline_cursor import (
    TimelineCursor,
    encode_cursor_from_log,
    parse_timeline_cursor_param,
)


class JobDetailTimelineCursorService:
    """Parse and emit opaque timeline cursors (newest-first keyset)."""

    def parse_request_cursor(self, request: Any | None) -> TimelineCursor | None:
        """Parse ``?cursor=`` from a DRF request."""
        return parse_timeline_cursor_param(request)

    def parse_cursor_token(self, raw_cursor: str | None) -> TimelineCursor | None:
        """
        Parse a raw cursor string (not tied to HTTP request).

        Returns None for first page or blank token.
        """

        class _Params:
            query_params = {}

        params = _Params()
        params.query_params = {'cursor': (raw_cursor or '').strip()}
        return parse_timeline_cursor_param(params)

    def encode_next_cursor(self, last_log_row: Any | None) -> str:
        """Opaque cursor for the next (older) page."""
        token = encode_cursor_from_log(last_log_row)
        return token or ''

    def validate_cursor_token(self, raw_cursor: str | None) -> bool:
        """Return False for malformed cursor tokens."""
        token = (raw_cursor or '').strip()
        if not token:
            return True
        return self.parse_cursor_token(token) is not None

    @staticmethod
    def cursor_sort_key(cursor: TimelineCursor) -> tuple:
        """Stable tie-break helper for tests."""
        return (cursor.log_date, cursor.log_id)
