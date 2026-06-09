"""Shared helpers for tenant portal EAL list tables (search, column filters, pagination)."""

from __future__ import annotations

from django.core.paginator import Paginator
from django.db.models import Q

LIST_PAGE_SIZE = 10


def eal_column_filter_values(request) -> dict[int, str]:
    """Parse ``filter_<col_index>`` query params from the request."""
    values: dict[int, str] = {}
    for key, val in request.GET.items():
        if not key.startswith('filter_'):
            continue
        try:
            idx = int(key[7:])
        except ValueError:
            continue
        text = (val or '').strip()
        if text:
            values[idx] = text
    return values


def apply_eal_column_filters(queryset, request, column_field_map: dict[int, str]):
    """Apply ``filter_<col_index>`` icontains filters using *column_field_map*."""
    for col_index, field_name in column_field_map.items():
        val = (request.GET.get(f'filter_{col_index}') or '').strip()
        if val:
            queryset = queryset.filter(**{f'{field_name}__icontains': val})
    return queryset


def apply_eal_column_sort(
    queryset,
    request,
    sort_col_field_map: dict[int, str],
    *,
    default_order=('-created_at',),
):
    """Order queryset using ``sort_col`` / ``sort_dir`` from the request."""
    try:
        sort_col = int(request.GET.get('sort_col') or 0)
    except (TypeError, ValueError):
        sort_col = 0

    sort_dir = (request.GET.get('sort_dir') or 'asc').strip().lower()
    field = sort_col_field_map.get(sort_col)
    if not field:
        if isinstance(default_order, (list, tuple)):
            return queryset.order_by(*default_order)
        return queryset.order_by(default_order)

    if sort_dir == 'desc':
        return queryset.order_by(f'-{field}')
    return queryset.order_by(field)


def paginate_tenant_list(request, queryset, *, per_page: int = LIST_PAGE_SIZE):
    """
    Paginate *queryset* and return ``(page, context_dict)`` for templates.

    *context_dict* includes pagination_start/end/total, page links, and prev/next URLs.
    """
    paginator = Paginator(queryset, per_page)
    try:
        page_no = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page_no = 1
    page = paginator.get_page(page_no)

    total_count = paginator.count
    if total_count == 0:
        ps, pe = 0, 0
    else:
        ps = (page.number - 1) * paginator.per_page + 1
        pe = ps + len(page.object_list) - 1

    def _page_url(page_num):
        q = request.GET.copy()
        q.pop('stype', None)
        try:
            pn = int(page_num)
        except (TypeError, ValueError):
            pn = 1
        if pn > 1:
            q['page'] = str(pn)
        else:
            q.pop('page', None)
        return '?' + q.urlencode()

    return page, {
        'pagination_page_links': [(n, _page_url(n)) for n in page.paginator.page_range],
        'pagination_prev_url': _page_url(page.previous_page_number()) if page.has_previous() else None,
        'pagination_next_url': _page_url(page.next_page_number()) if page.has_next() else None,
        'pagination_start': ps,
        'pagination_end': pe,
        'pagination_total': total_count,
    }


def prepare_eal_list(
    request,
    queryset,
    *,
    search_q: str = '',
    search_fields: list[str] | None = None,
    column_field_map: dict[int, str] | None = None,
    sort_col_field_map: dict[int, str] | None = None,
    default_order=('-created_at',),
    per_page: int = LIST_PAGE_SIZE,
):
    """
    Apply global search, column filters, sort, and pagination.

    Returns ``(page, context_dict)`` where *context_dict* is ready to ``context.update()``.
    """
    sq = (search_q if search_q is not None else (request.GET.get('q') or '')).strip()
    if sq and search_fields:
        q_obj = Q()
        for field in search_fields:
            q_obj |= Q(**{f'{field}__icontains': sq})
        queryset = queryset.filter(q_obj)

    if column_field_map:
        queryset = apply_eal_column_filters(queryset, request, column_field_map)

    if sort_col_field_map:
        queryset = apply_eal_column_sort(
            queryset,
            request,
            sort_col_field_map,
            default_order=default_order,
        )
    elif isinstance(default_order, (list, tuple)):
        queryset = queryset.order_by(*default_order)
    else:
        queryset = queryset.order_by(default_order)

    page, pagination_ctx = paginate_tenant_list(request, queryset, per_page=per_page)
    pagination_ctx['search_q'] = sq
    pagination_ctx['eal_column_filters'] = eal_column_filter_values(request)
    pagination_ctx['sort_col'] = request.GET.get('sort_col', '')
    pagination_ctx['sort_dir'] = request.GET.get('sort_dir', '')
    return page, pagination_ctx
