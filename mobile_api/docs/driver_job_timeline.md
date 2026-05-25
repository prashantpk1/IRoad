# Driver Job Detail — Timeline APIs

Scalable, cursor-paginated operational history for execution screens.

## Endpoints

| Method | Path |
|--------|------|
| `GET` | `/api/v1/mobile/driver/jobs/shipments/{shipment_id}/timeline/` |
| `GET` | `/api/v1/mobile/driver/jobs/movements/{movement_id}/timeline/` |

**Capability:** `mobile.driver.jobs`  
**Pagination:** cursor only (no `page` / offset)

## Query parameters

| Param | Default | Max |
|-------|---------|-----|
| `page_size` | 20 (`MOBILE_JOB_TIMELINE_DEFAULT_PAGE_SIZE`) | 50 |
| `cursor` | — | Opaque; from previous `pagination.next_cursor` |

Invalid `cursor` → `400` / `invalid_cursor`.

## Query planner (shipment vs movement)

| Scope | Strategy | Indexes |
|-------|----------|---------|
| **Shipment** | `UNION ALL` of direct `shipment_id` rows and `truck_movement_id IN (movements for shipment)` rows (deduped via `exclude(shipment_id=…)` on the movement branch). Cursor filter applied on **each** branch before union. Page rows are re-fetched with `select_related` after the union slice. | `tenant_oal_ship_drv_dt_id_idx`, `tenant_oal_move_drv_dt_id_idx`, `tenant_tml_shipment_idx` |
| **Movement** | Single `truck_movement_id = ?` filter (no OR, no union). | `tenant_oal_move_drv_dt_id_idx` |

Bounded preview / execution timeline scans use subquery `IN` (same semantics, single query) via `shipment_action_log_scope_q` — not `truck_movement__shipment_id`.

Deploy indexes: `migrate_job_detail_tenants` / migrations `0093`–`0095`. EXPLAIN audit: `python manage.py job_detail_explain_audit --schema=<tenant>`.

## Response shape

```json
{
  "success": true,
  "data": {
    "timeline": {
      "job_type": "shipment",
      "job_id": "uuid",
      "job_no": "SH-001",
      "items": [
        {
          "log_id": "uuid",
          "log_no": "OAL-0001",
          "action_name": "Depart In Transit",
          "action_code": "A5",
          "execution_time": "2026-05-21T10:00:00+00:00",
          "driver_name": "Ahmed Ali",
          "gps": {
            "latitude": "24.7136",
            "longitude": "46.6753",
            "map_link": "https://maps.google.com/?q=24.7136,46.6753"
          },
          "notes": "Departed yard",
          "media_previews": [
            {
              "media_id": "uuid",
              "line_no": 1,
              "media_type": "photo",
              "description": "Gate photo",
              "captured_at": null,
              "preview_url": "https://…/media/…",
              "has_file": true
            }
          ],
          "media_count": 1,
          "status_impacts": {
            "shipment": "In Transit",
            "movement": null,
            "booking": null
          },
          "events": {
            "is_pod": false,
            "is_cod": false,
            "is_reversal": false,
            "is_status_impact": true
          }
        }
      ],
      "pagination": {
        "mode": "cursor",
        "page_size": 20,
        "count": 1,
        "has_next": true,
        "next_cursor": "eyJ2IjoxLCJsb2dfZGF0ZSI6Li4uLCJsb2dfaWQiOiIuLi4ifQ"
      }
    }
  }
}
```

## Architecture

| Layer | Module |
|-------|--------|
| Cursor | `mobile_api/helpers/timeline_cursor.py` |
| Params | `mobile_api/helpers/timeline_params.py` |
| Projections | `mobile_api/helpers/timeline_projections.py` |
| Query scope | `iroad_tenants/services/timeline_query.py` (UNION / subquery IN) → `timeline_service.scoped_action_log_queryset` |
| Orchestration | `mobile_api/services/driver_job_timeline_service.py` |
| Views | `mobile_api/views/driver_job_timeline.py` |

## Scalability rules

- Keyset on `(log_date, log_id)` — stable under concurrent writes.
- Fetch `page_size + 1` to compute `has_next` without COUNT.
- One batched media query per page; max `MOBILE_JOB_TIMELINE_MEDIA_PER_LOG` previews per log (default 3).
- No binary payloads — `preview_url` only when file exists.
- Driver-scoped logs (`driver_id` filter + job ownership via `_load_shipment` / `_load_movement`).

## vs Job Detail preview

| Feature | Detail `timeline_preview` | Timeline API |
|---------|-------------------------|--------------|
| Max rows | 15 (config) | 20–50 per page |
| Pagination | None | Cursor |
| Media | No | Capped previews |
| Use case | Screen bootstrap | Full history feed |
