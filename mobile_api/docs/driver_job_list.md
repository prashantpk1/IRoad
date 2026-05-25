# Driver Job List (mobile API)

Phase 1: **separate** shipment and movement feeds — lightweight job cards, page pagination, no unified mixed feed, no timelines.

**Job card contract:** [driver_job_card_contract.md](./driver_job_card_contract.md)

**Pagination & filters:** [driver_job_list_pagination.md](./driver_job_list_pagination.md)

**Performance:** [driver_job_list_performance.md](./driver_job_list_performance.md)

**Latest / next action:** [driver_job_list_actions.md](./driver_job_list_actions.md)

**Security & RBAC:** [driver_job_list_security.md](./driver_job_list_security.md)

**Production hardening:** [driver_job_list_production.md](./driver_job_list_production.md)

## Endpoints

| Method | Path | Capability |
|--------|------|------------|
| `GET` | `/api/v1/mobile/driver/jobs/summary/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/shipments/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/shipments/active/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/shipments/completed/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/shipments/cancelled/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/shipments/pod-pending/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/shipments/cod-pending/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/movements/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/movements/active/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/movements/completed/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/movements/cancelled/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/movements/empty/` | `mobile.driver.jobs` |

**Auth:** `Authorization: Bearer <access_token>`. Tenant from JWT `tenant_schema`.

## Summary API

`GET /api/v1/mobile/driver/jobs/summary/` — tab-aligned badge counts (8 fields). Full contract: [driver_job_list_summary.md](./driver_job_list_summary.md).

```json
"data": {
  "counters": {
    "active_shipments": 0,
    "completed_shipments": 0,
    "cancelled_shipments": 0,
    "active_movements": 0,
    "completed_movements": 0,
    "cancelled_movements": 0,
    "pod_pending": 0,
    "cod_pending": 0
  },
  "entity_types": ["shipment", "movement"]
}
```

## Shipment list API contract

**Auth:** `Authorization: Bearer <access_token>`

**Success envelope (paginated):**

```json
{
  "status": 1,
  "message": "Active shipment jobs loaded successfully.",
  "message_key": "mobile.jobs.shipments_active_success",
  "data": {
    "items": [ { "job_id": "...", "job_type": "shipment", "shipment_no": "SH-001", ... } ],
    "total_records": 42,
    "total_pages": 5,
    "current_page": 1,
    "page_size": 10,
    "meta": {
      "tab": "active",
      "queue": "none",
      "sort": "updated_desc",
      "entity_type": "shipment",
      "tab_locked": true,
      "queue_locked": false
    }
  },
  "meta": { "request_id": "...", "timestamp": "...", "locale": "en" }
}
```

**Shipment job card fields (lightweight):** `job_id`, `job_type`, `shipment_id`, `shipment_no`, `current_status`, `booking_no`, `order_type`, `route`, `truck`, `route_summary`, `latest_action_summary`, `next_action_hint`, `pod_status`, `cod_status`, `collection_status`, `priority` (`needs_pod`, `needs_cod`, `is_active`), `updated_at`, `created_at`, `shipment_date`. Actions are batched per page when `include_actions` is enabled (default).

Path routes lock `tab` and/or `queue` — query `tab` / `queue` cannot override locked dimensions.

### Movement job card fields

`job_id`, `job_type`, `movement_id`, `movement_no`, `current_status`, `movement_source`, `empty_move_reason`, `is_empty_move`, `shipment_id`, `shipment_no`, `from_location`, `to_location`, `route`, `truck`, `route_summary`, `priority`, timestamps. Route uses linked shipment addresses when present, else movement location points.

### Movement status taxonomy (`operational_status.py`)

| Tab | Statuses |
|-----|----------|
| `active` | Scheduled, In Progress |
| `completed` | Completed |
| `cancelled` | Cancelled |
| `empty` queue | `movement_source=empty` OR non-empty `empty_move_reason` (on active tab) |

## Query parameters (list endpoints)

| Param | Values | Default |
|-------|--------|---------|
| `tab` | `active`, `completed`, `cancelled`, `all` | `active` |
| `queue` | `none`, `pod_pending`, `cod_pending`, `delivery_pending`, `pickup_pending`, `empty_move` | `none` |
| `q` | search string | — |
| `sort` | `updated_desc`, `updated_asc`, `created_desc`, `number_desc`, `number_asc` | `updated_desc` |
| `page`, `page_size` | pagination | settings defaults |
| `date_from`, `date_to` | ISO dates (filter on `updated_at`) | — |

## Architecture

```
helpers/
  operational_status.py   # status sets + driver_shipment_scope_q / driver_movement_scope_q
  job_list_query.py       # base querysets (only + select_related)
  job_list_filters.py     # apply_job_filters, parse_job_list_filters
  job_list_ordering.py    # apply_job_ordering
  job_list_projections.py # route, priority, next_action (no dashboard payload)
  job_list_security.py    # JOBS_API_PREFIX, tenant binding

services/
  driver_job_list_service.py      # resolve_secure_job_list_context, build_job_summary
  driver_shipment_list_service.py # list_driver_shipments, build_shipment_job_card
  driver_movement_list_service.py # list_driver_movements, build_movement_job_card
  driver_job_list_dto.py          # TypedDict contracts

views/driver_jobs.py
serializers/driver_job_list.py
```

## Driver scope

- **Shipments:** `driver_id` OR `booking.assigned_driver_id` (same as dashboard).
- **Movements:** `driver_id` on `TenantTruckMovementLog`.

## Pagination envelope

Uses `MobileApiPagination` — `data.items`, `data.total_records`, `data.current_page`, `data.page_size`, plus `data.meta` (`tab`, `queue`, `sort`, `entity_type`).

## Phase 2 (not implemented)

- Unified mixed job feed
- Cursor pagination / `updated_since` delta sync
- Per-row `latest_action_summary` on list cards
