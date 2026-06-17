"""Shared helpers for tenant portal EAL list tables (search, column filters, pagination)."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable
from typing import Any

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.db.models import Q, TextField
from django.db.models.functions import Cast

LIST_PAGE_SIZE = 10

ColumnFilterHook = Callable[[Any, str], Any]


def _param_key(name: str, prefix: str = '') -> str:
    return f'{prefix}{name}' if prefix else name


def eal_column_filter_values(request, prefix: str = '') -> dict[int, str]:
    """Parse ``[prefix]filter_<col_index>`` query params from the request."""
    filter_prefix = _param_key('filter_', prefix)
    values: dict[int, str] = {}
    for key, val in request.GET.items():
        if not key.startswith(filter_prefix):
            continue
        try:
            idx = int(key[len(filter_prefix):])
        except ValueError:
            continue
        text = (val or '').strip()
        if text:
            values[idx] = text
    return values


def copy_eal_list_params(
    request,
    *,
    set_params: dict[str, str | None] | None = None,
    remove: list[str] | None = None,
    omit_page: bool = True,
    prefix: str = '',
) -> str:
    """Build a query string preserving current list filters/search/sort."""
    q = request.GET.copy()
    q.pop('stype', None)
    if omit_page:
        q.pop(_param_key('page', prefix), None)
    for key in remove or []:
        q.pop(key, None)
    for key, value in (set_params or {}).items():
        if value is None or value == '':
            q.pop(key, None)
        else:
            q[key] = value
    encoded = q.urlencode()
    return f'?{encoded}' if encoded else ''


def _parse_boolean_filter(val: str) -> bool | None:
    v = val.strip().lower()
    if v in ('yes', 'y', 'true', '1'):
        return True
    if v in ('no', 'n', 'false', '0'):
        return False
    return None


def _apply_text_column_filter(queryset, field_name: str, val: str):
    return queryset.filter(**{f'{field_name}__icontains': val})


def _apply_cast_text_column_filter(queryset, field_name: str, val: str, *, annotate_key: str):
    return queryset.annotate(
        **{annotate_key: Cast(field_name, TextField())},
    ).filter(**{f'{annotate_key}__icontains': val})


def apply_eal_column_filters(
    queryset,
    request,
    column_field_map: dict[int, str],
    *,
    prefix: str = '',
    column_filter_types: dict[int, str] | None = None,
    column_filter_hooks: dict[int, ColumnFilterHook] | None = None,
):
    """Apply ``[prefix]filter_<col_index>`` filters using *column_field_map*."""
    column_filter_types = column_filter_types or {}
    column_filter_hooks = column_filter_hooks or {}

    for col_index, field_name in column_field_map.items():
        val = (request.GET.get(_param_key(f'filter_{col_index}', prefix)) or '').strip()
        if not val:
            continue

        hook = column_filter_hooks.get(col_index)
        if hook is not None:
            queryset = hook(queryset, val)
            continue

        ftype = column_filter_types.get(col_index, 'text')
        annotate_key = f'_eal_filter_{col_index}'

        if ftype == 'boolean':
            parsed = _parse_boolean_filter(val)
            if parsed is None:
                continue
            queryset = queryset.filter(**{field_name: parsed})
        elif ftype == 'file':
            vlow = val.strip().lower()
            if vlow in ('yes', 'y', 'true', '1', 'file'):
                queryset = queryset.exclude(**{f'{field_name}': ''}).filter(
                    **{f'{field_name}__isnull': False},
                )
            elif vlow in ('no', 'n', 'false', '0'):
                queryset = queryset.filter(
                    Q(**{field_name: ''}) | Q(**{f'{field_name}__isnull': True}),
                )
            else:
                queryset = _apply_text_column_filter(queryset, field_name, val)
        elif ftype in ('date', 'datetime', 'number'):
            queryset = _apply_cast_text_column_filter(
                queryset,
                field_name,
                val,
                annotate_key=annotate_key,
            )
        else:
            queryset = _apply_text_column_filter(queryset, field_name, val)
    return queryset


def apply_eal_column_sort(
    queryset,
    request,
    sort_col_field_map: dict[int, str],
    *,
    default_order=('-created_at',),
    prefix: str = '',
):
    """Order queryset using ``[prefix]sort_col`` / ``[prefix]sort_dir`` from the request."""
    try:
        sort_col = int(request.GET.get(_param_key('sort_col', prefix)) or 0)
    except (TypeError, ValueError):
        sort_col = 0

    sort_dir = (request.GET.get(_param_key('sort_dir', prefix)) or 'asc').strip().lower()
    field = sort_col_field_map.get(sort_col)
    if not field:
        if isinstance(default_order, (list, tuple)):
            return queryset.order_by(*default_order)
        return queryset.order_by(default_order)

    if sort_dir == 'desc':
        return queryset.order_by(f'-{field}')
    return queryset.order_by(field)


def paginate_tenant_list(
    request,
    queryset,
    *,
    per_page: int = LIST_PAGE_SIZE,
    prefix: str = '',
):
    """
    Paginate *queryset* and return ``(page, context_dict)`` for templates.

    *context_dict* includes pagination_start/end/total, page links, and prev/next URLs.
    """
    page_key = _param_key('page', prefix)
    paginator = Paginator(queryset, per_page)
    try:
        page_no = max(1, int(request.GET.get(page_key) or 1))
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
            q[page_key] = str(pn)
        else:
            q.pop(page_key, None)
        encoded = q.urlencode()
        return f'?{encoded}' if encoded else ''

    return page, {
        'pagination_page_links': [(n, _page_url(n)) for n in page.paginator.page_range],
        'pagination_prev_url': _page_url(page.previous_page_number()) if page.has_previous() else None,
        'pagination_next_url': _page_url(page.next_page_number()) if page.has_next() else None,
        'pagination_start': ps,
        'pagination_end': pe,
        'pagination_total': total_count,
    }


def get_list_search_q(request, *legacy_keys: str, prefix: str = '') -> str:
    """Resolve global list search from ``q`` or legacy param names (e.g. ``search``)."""
    q_val = (request.GET.get(_param_key('q', prefix)) or '').strip()
    if q_val:
        return q_val
    for key in legacy_keys:
        val = (request.GET.get(key) or '').strip()
        if val:
            return val
    return ''


def _resolved_search_q(request, search_q, *, prefix: str = '') -> str:
    """Resolve global search text from explicit *search_q* or ``[prefix]q`` GET param."""
    if search_q is not None:
        return (search_q or '').strip()
    q_key = _param_key('q', prefix)
    return (request.GET.get(q_key) or '').strip()


def build_eal_list_queryset(
    request,
    queryset,
    *,
    search_q: str | None = None,
    search_fields: list[str] | None = None,
    column_field_map: dict[int, str] | None = None,
    sort_col_field_map: dict[int, str] | None = None,
    default_order=('-created_at',),
    prefix: str = '',
    column_filter_types: dict[int, str] | None = None,
    column_filter_hooks: dict[int, ColumnFilterHook] | None = None,
):
    """Apply global search, column filters, and sort (no pagination)."""
    sq = _resolved_search_q(request, search_q, prefix=prefix)
    if sq and search_fields:
        q_obj = Q()
        for field in search_fields:
            q_obj |= Q(**{f'{field}__icontains': sq})
        queryset = queryset.filter(q_obj)

    if column_field_map:
        queryset = apply_eal_column_filters(
            queryset,
            request,
            column_field_map,
            prefix=prefix,
            column_filter_types=column_filter_types,
            column_filter_hooks=column_filter_hooks,
        )

    if sort_col_field_map:
        queryset = apply_eal_column_sort(
            queryset,
            request,
            sort_col_field_map,
            default_order=default_order,
            prefix=prefix,
        )
    elif isinstance(default_order, (list, tuple)):
        queryset = queryset.order_by(*default_order)
    else:
        queryset = queryset.order_by(default_order)

    return queryset


def prepare_eal_list(
    request,
    queryset,
    *,
    search_q: str | None = None,
    search_fields: list[str] | None = None,
    column_field_map: dict[int, str] | None = None,
    sort_col_field_map: dict[int, str] | None = None,
    default_order=('-created_at',),
    per_page: int = LIST_PAGE_SIZE,
    prefix: str = '',
    column_filter_types: dict[int, str] | None = None,
    column_filter_hooks: dict[int, ColumnFilterHook] | None = None,
):
    """
    Apply global search, column filters, sort, and pagination.

    Returns ``(page, context_dict)`` where *context_dict* is ready to ``context.update()``.
    """
    sq = _resolved_search_q(request, search_q, prefix=prefix)
    queryset = build_eal_list_queryset(
        request,
        queryset,
        search_q=search_q,
        search_fields=search_fields,
        column_field_map=column_field_map,
        sort_col_field_map=sort_col_field_map,
        default_order=default_order,
        prefix=prefix,
        column_filter_types=column_filter_types,
        column_filter_hooks=column_filter_hooks,
    )

    page, pagination_ctx = paginate_tenant_list(
        request,
        queryset,
        per_page=per_page,
        prefix=prefix,
    )
    pagination_ctx['search_q'] = sq
    pagination_ctx['eal_column_filters'] = eal_column_filter_values(request, prefix=prefix)
    pagination_ctx['sort_col'] = request.GET.get(_param_key('sort_col', prefix), '')
    pagination_ctx['sort_dir'] = request.GET.get(_param_key('sort_dir', prefix), '')
    pagination_ctx['param_prefix'] = prefix
    return page, pagination_ctx


EXPORT_SELECTED_PARAM = 'selected'


def parse_export_selected_values(request) -> list[str]:
    """Parse comma-separated export selection ids from the query string."""
    raw = (request.GET.get(EXPORT_SELECTED_PARAM) or '').strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(',') if part.strip()]


def apply_list_export_selection(queryset, request, field_name: str):
    """Restrict export queryset to explicitly selected row ids when provided."""
    selected = parse_export_selected_values(request)
    if not selected or not field_name:
        return queryset
    return queryset.filter(**{f'{field_name}__in': selected})


def build_csv_http_response(
    filename: str,
    headers: list[str],
    rows: Iterable[list],
) -> HttpResponse:
    """Return a UTF-8 CSV download (BOM included for Excel)."""
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
