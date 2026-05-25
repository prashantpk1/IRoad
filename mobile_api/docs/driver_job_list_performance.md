# Driver job list — performance architecture

PostgreSQL tenant schema. Targets: **≤12 queries** per paginated list page (default `page_size=10`).

## Query budget (paginated list)

| Step | Queries | Notes |
|------|---------|--------|
| List slice | 1 | `LIMIT/OFFSET` on driver-scoped queryset |
| COUNT | 0–1 | Skipped when `include_total=0` |
| Latest action | 0–1 | One `DISTINCT ON` for page parent ids |
| Next-action hints | 0 | In-memory from loaded rows |
| Card projection | 0 | Python dict build |
| Sanitize (optional) | 0–2 | Preloaded scope PK sets when enabled |

**Not used:** timelines, per-row `fetch_latest_action_log()`, portal detail serializers, correlated subquery on full list (default off).

## Batching strategies

### Latest action (default `MOBILE_JOB_LIST_PAGE_ACTION_BATCH=True`)

After pagination, one query per entity type:

```sql
SELECT DISTINCT ON (shipment_id) ...
FROM tenant_operation_action_logs
WHERE driver_id = $driver AND shipment_id IN ($page_ids)
ORDER BY shipment_id, log_date DESC, created_at DESC;
```

Uses index `tenant_oal_ship_drv_date_idx`. Movement path uses `tenant_oal_move_drv_date_idx` + `truck_movement_id`.

Legacy path (`MOBILE_JOB_LIST_PAGE_ACTION_BATCH=False`): correlated `Subquery` annotation on **every** filtered row (slow COUNT).

### Summary counters

`build_job_list_counters`: 2 conditional `aggregate()` calls — unchanged.

## Queryset optimizations

| Area | Optimization |
|------|----------------|
| Driver scope | `secure_*_queryset_for_driver` — indexed `driver_id` / booking assignment |
| `only()` | Shipment/movement card columns only |
| Joins | Removed `truck__truck_type`; movement `shipment` via `Prefetch` + `only()` |
| Search | `istartswith` / `iexact` on `shipment_no` / `movement_no`; movement uses `Subquery` not join OR |
| Dates | `updated_at` range (not `__date` lookup) |
| Ordering | Default `-updated_at`; `priority_desc` adds `Case` annotation — use only when needed |
| Pagination | `MobileJobListPagination` caps `page_size`; optional COUNT skip |

## Serializer depth

- Cards built as **flat dicts** in `job_card_projections` (no nested portal trees).
- `MOBILE_JOB_LIST_FAST_SERIALIZE=True`: skip DRF re-validation on list items.
- Nested `route` / `truck` / `indicators` mirrors are optional compact copies.

## Indexes (tenant migrations)

| Index | Use |
|-------|-----|
| `tenant_ship_driver_status_idx` | Tab filters (active/completed/cancelled) |
| `tenant_ship_drv_stat_upd_idx` | `sort=updated_desc` |
| `tenant_ship_stat_pod_idx` / `tenant_ship_stat_coll_idx` | POD/COD queues |
| `tenant_ship_drv_no_idx` | Prefix search |
| `tenant_tml_driver_status_idx` | Movement tabs |
| `tenant_tml_drv_stat_upd_idx` | Movement sort |
| `tenant_tml_drv_mno_idx` | Movement number search |
| `tenant_oal_ship_drv_date_idx` | Latest action batch (shipment) |
| `tenant_oal_move_drv_date_idx` | Latest action batch (movement) |

Apply: `migrate tenant_workspace` through `0089`.

## EXPLAIN recommendations

Run inside tenant schema (`schema_context`):

### Active shipments list

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT ... FROM tenant_shipments
WHERE (driver_id = $1 OR booking_id IN (
  SELECT booking_id FROM tenant_bookings WHERE assigned_driver_id = $1
))
AND shipment_status IN ('Loaded', 'Created', 'In Transit', ...)
ORDER BY updated_at DESC
LIMIT 10;
```

Expect: `Index Scan` or `Bitmap Index Scan` on `(driver, shipment_status)` or `(driver, updated_at)` — avoid `Seq Scan` on large tenants.

### Latest action batch

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT ON (shipment_id) ...
FROM tenant_operation_action_logs
WHERE driver_id = $1 AND shipment_id = ANY($2::uuid[])
ORDER BY shipment_id, log_date DESC;
```

Expect: `Index Scan` using `tenant_oal_ship_drv_date_idx`.

### POD pending queue

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*) FROM tenant_shipments
WHERE <driver_scope> AND shipment_status IN (<active>) AND pod_status <> 'Compliant';
```

Expect: composite `(shipment_status, pod_status)` helpful after scope filter.

## Client tuning

| Query param | Effect |
|-------------|--------|
| `include_total=0` | Skip `COUNT(*)` on large histories |
| `include_actions=0` | Skip latest-action batch |
| `page_size` | Capped at `MOBILE_API_MAX_PAGE_SIZE` (100) |

## Settings

| Setting | Default |
|---------|---------|
| `MOBILE_JOB_LIST_PAGE_ACTION_BATCH` | `True` |
| `MOBILE_JOB_LIST_FAST_SERIALIZE` | `True` |
| `MOBILE_JOB_LIST_INCLUDE_TOTAL_DEFAULT` | `False` |
| `MOBILE_API_DEFAULT_PAGE_SIZE` | `10` |

## Anti-patterns (prevented)

- N+1: no per-row action fetch; single DISTINCT ON per page
- Timeline loading: not implemented on list endpoints
- Deep nested serializers: flat projections + fast serialize
- Unbounded lists: pagination required; max page size enforced
