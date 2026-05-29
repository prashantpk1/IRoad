"""
mobile_api/list_pagination.py

Page-number pagination for mobile list endpoints (History, Wallet, etc.).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence, TypeVar

from django.conf import settings

T = TypeVar('T')


def _int_setting(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


MOBILE_LIST_DEFAULT_PAGE_SIZE = _int_setting('MOBILE_API_DEFAULT_PAGE_SIZE', 10)
MOBILE_LIST_MAX_PAGE_SIZE = _int_setting('MOBILE_API_MAX_PAGE_SIZE', 100)


@dataclass(frozen=True)
class ListPaginationParams:
    page: int
    page_size: int


def parse_list_pagination(
    page_raw: str | None = None,
    page_size_raw: str | None = None,
) -> ListPaginationParams:
    """Parse ``page`` and ``page_size`` query params with mobile defaults."""
    try:
        page = int(str(page_raw or '').strip() or '1')
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)

    try:
        page_size = int(str(page_size_raw or '').strip() or str(MOBILE_LIST_DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        page_size = MOBILE_LIST_DEFAULT_PAGE_SIZE
    page_size = max(1, min(page_size, MOBILE_LIST_MAX_PAGE_SIZE))

    return ListPaginationParams(page=page, page_size=page_size)


def paginate_sequence(
    rows: Sequence[T],
    *,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Slice an in-memory sequence and return standard pagination metadata."""
    total = len(rows)
    if page_size <= 0:
        page_size = MOBILE_LIST_DEFAULT_PAGE_SIZE
    total_pages = math.ceil(total / page_size) if total else 0
    start = (page - 1) * page_size
    end = start + page_size
    page_items = list(rows[start:end])
    return {
        'items': page_items,
        'count': len(page_items),
        'results_found': total,
        'total_records': total,
        'total_pages': total_pages,
        'current_page': page,
        'page_size': page_size,
    }


def empty_pagination_page(*, page: int, page_size: int) -> dict[str, Any]:
    """Pagination shell for ``count_only`` responses."""
    return {
        'items': [],
        'count': 0,
        'results_found': 0,
        'total_records': 0,
        'total_pages': 0,
        'current_page': page,
        'page_size': page_size,
    }
