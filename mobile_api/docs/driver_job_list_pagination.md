# Driver job list — pagination & filtering

Phase 1 scalable mobile filtering for shipment and movement feeds.

## Pipeline

```
Request → parse filters/sort/dates
       → build_driver_job_list_queryset()
            1. base_*_job_queryset (driver scope + only/select_related)
            2. apply_job_filters (tab, queue, search)
            3. apply_job_date_filters (updated_at or operational date)
            4. apply_job_ordering
       → MobileApiPagination
```

**Modules**

| Module | Role |
|--------|------|
| `job_list_filters.py` | Tab/queue taxonomy, `JobListFilters`, status Q-objects |
| `job_list_search.py` | Prefix/exact search (`istartswith` / `iexact`), movement subquery |
| `job_list_dates.py` | ISO date validation, timestamp ranges on `updated_at` |
| `job_list_ordering.py` | Stable sorts + `priority_desc` operational ordering |
| `job_list_filter_service.py` | Central queryset builder + response meta |
| `job_list_query.py` | Driver-scoped base querysets |

## Tabs (status filters)

| Tab | Shipments | Movements |
|-----|-----------|-----------|
| `active` | In-flight statuses | Scheduled / In Progress |
| `completed` | Delivered / Closed | Completed |
| `cancelled` | Cancelled | Cancelled |
| `all` | No status filter | No status filter |

Path-locked routes override `tab` query param (e.g. `/shipments/active/`).

## Queues (operational filters)

| Queue | Entity | Semantics |
|-------|--------|-----------|
| `pod_pending` | Shipment | Active + POD not compliant |
| `cod_pending` | Shipment | Active COD + collection pending |
| `empty_move` | Movement | `movement_source=empty` or `empty_move_reason` set |
| `delivery_pending` | Shipment | Status At Delivery |
| `pickup_pending` | Shipment | Loaded / Created |

Dedicated paths: `/shipments/pod-pending/`, `/shipments/cod-pending/`, `/movements/empty/`.

## Search

| Param | Alias | Behavior |
|-------|-------|----------|
| `q` | `search` | Min length 2 |

- **Shipments:** `shipment_no` prefix/exact (`istartswith` / `iexact`). Booking no only when term looks like `BK…` / `BOOK…`.
- **Movements:** `movement_no` prefix/exact; linked shipment via **subquery** on driver-scoped shipments (avoids `shipment__shipment_no__icontains` OR join).

## Dates

| Param | Values |
|-------|--------|
| `date_from`, `date_to` | `YYYY-MM-DD` (inclusive operational dates; `updated_at` uses half-open day range) |
| `date_field` | `updated` (default) \| `operational` (`shipment_date` / `movement_date`) |

Max span: 366 days (auto-clamped).

## Sorting

| `sort` | Description |
|--------|-------------|
| `updated_desc` | Default — newest activity first |
| `updated_asc` | Oldest updates first |
| `created_desc` | Newest created |
| `number_asc` / `number_desc` | Job number |
| `priority_desc` | Shipments: POD → COD → other active → rest |
| `status_asc` | Status label, then recency |

## Pagination

Uses `MobileJobListPagination` (extends mobile envelope):

- `page` (default 1)
- `page_size` (default from `MOBILE_API_DEFAULT_PAGE_SIZE`, max `MOBILE_API_MAX_PAGE_SIZE`)
- `include_total=0` — skip `COUNT(*)` (`total_records` / `total_pages` omitted)

Response `data`: `items`, `current_page`, `page_size`, optional `total_records` / `total_pages`, plus `meta` echoing filters.

See [driver_job_list_performance.md](./driver_job_list_performance.md) for query budget and EXPLAIN notes.

## Driver scope

Applied in `base_*_job_queryset` via `dashboard_security`:

- Shipments: `driver_id` OR `booking.assigned_driver_id`
- Movements: `driver_id`

Never filter by JWT alone.

## Index recommendations

Existing (0083, 0086):

- `(driver, shipment_status)`, `(driver, shipment_status, -updated_at)`
- `(driver, status, -updated_at)` on movements
- `(shipment_status, pod_status)`, `(shipment_status, collection_status)`

Added (0088):

- `(driver, shipment_no)` — prefix search within driver scope
- `(driver, movement_no)` — movement number lookup
- `(driver, movement_source)` — empty-move queue

**Avoid:** `icontains` on list paths, unbounded `OR` across unrelated tables, `updated_at__date` lookups (use timestamp range instead).

## Apply migration

```bash
python manage.py migrate tenant_workspace 0088
```
