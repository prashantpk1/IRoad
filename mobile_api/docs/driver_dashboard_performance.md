# Driver Home Dashboard — Performance Architecture

## Goals

- **Low mobile latency**: bounded query count, capped row fetches, no timeline scans
- **Scalable driver scope**: every query filtered by `driver_id` / shipment scope
- **Minimal DB load**: aggregates over loops, request-level deduplication, optional Redis cache

## Query budget (after optimization)

| Phase | Queries (typical) | Notes |
|-------|-------------------|--------|
| Auth (`_resolve_driver_context`) | 2 | Tenant user + driver |
| Welcome context | 3–4 | Assignment, org profile, driver settings (read-only `.first()`) |
| Counters | 2 | One shipment `aggregate()`, one movement `aggregate()` |
| Current job | 2–3 | Reuses cached latest shipment; movement + action log |
| Notifications | 2–3 tenant + 1–2 public | Single `TenantRegistry` via `tenant_profile_id`; memoized on request |
| Recent activity | 3–4 full / 2–3 summary | Summary skips POD source when configured |
| Serializer | 0 DB | Fast path returns pre-built dict |

**Tenant schema (typical full dashboard): ~14–17** (down from ~18–22)  
**Public schema: ~1–2** (down from ~3–4)

## Optimizations implemented

### 1. Query deduplication (`DashboardBuildState`)

- **Latest active shipment** fetched once, shared by `current_job` and `recent_activity` (injected top shipment row).
- **Shipment scope PK list** materialized once per request for POD `__in` filter (replaces correlated subquery).
- **`tenant_profile_id`** resolved in welcome context and passed to notifications/FCM (no duplicate `TenantRegistry` queries).

### 2. Counter aggregates

- Removed `pk__in` subquery wrapper; filters use `driver_shipment_scope_q` directly (same row cardinality, less planner work).

### 3. ORM column pruning

- `.only()` on: current job shipment, action logs, activity sources, inbox rows, push receipts, org profile, driver settings.

### 4. Recent activity

- POD filter: `is_delivery_note=True` OR `document_type__iexact='POD'` (index-friendly vs `icontains`).
- Summary variant: optional skip of POD query (`MOBILE_API_DASHBOARD_SUMMARY_SKIP_POD_ACTIVITY`, default `True`).

### 5. Serializer depth

- `MOBILE_API_DASHBOARD_FAST_SERIALIZE=True` (default): skip re-walking 15 nested DRF serializers; trust service-built dict.

### 6. Optional Redis cache

- `MOBILE_API_DASHBOARD_CACHE_TTL_SECONDS` (default `0` = off).
- Key: `mobile:dashboard:v1:{schema}:{driver_id}:{variant}`.
- Use **15–30s** for summary polling; invalidate on driver mutations (future).

### 7. Composite indexes

**Tenant (`0086_dashboard_activity_query_indexes`):**

| Index | Table | Columns | Serves |
|-------|-------|---------|--------|
| `tenant_oal_driver_date_idx` | action logs | `driver, -log_date` | Activity feed by driver |
| `tenant_tml_driver_upd_idx` | movements | `driver, -updated_at` | Movement activity ordering |
| `tenant_tml_drv_stat_upd_idx` | movements | `driver, status, -updated_at` | Active movement fallback |
| `tenant_tml_ship_stat_upd_idx` | movements | `shipment, status, -updated_at` | Current job linked movement |
| `tenant_ship_drv_stat_upd_idx` | shipments | `driver, shipment_status, -updated_at` | Latest active job pick |
| `tenant_shipdoc_ship_dn_upd_idx` | documents | `shipment, is_delivery_note, -updated_at` | POD activity |

**Public (`0038_push_dashboard_lookup_indexes`):**

| Index | Serves |
|-------|--------|
| `comm_push_token_drv_lookup_idx` | FCM `device_token_registered` |
| `comm_push_rcpt_drv_lookup_idx` | Push receipt summary items |

Prior counter indexes remain in **0083**; current-job action log index in **0084**; inbox in **0085**.

## EXPLAIN / query plan guidance

Run on tenant schema (replace `:driver_id`):

```sql
-- Counters (shipment aggregate)
EXPLAIN ANALYZE
SELECT COUNT(*) FILTER (WHERE shipment_status IN (...)) AS active_shipments
FROM tenant_shipments
WHERE driver_id = :driver_id
   OR booking_id IN (
        SELECT booking_id FROM tenant_bookings WHERE assigned_driver_id = :driver_id
   );

-- Latest active job (should use tenant_ship_drv_stat_upd_idx)
EXPLAIN ANALYZE
SELECT shipment_id FROM tenant_shipments
WHERE (driver_id = :driver_id OR booking_id IN (...))
  AND shipment_status IN (...)
ORDER BY updated_at DESC
LIMIT 1;

-- Action activity (should use tenant_oal_driver_date_idx)
EXPLAIN ANALYZE
SELECT log_id FROM tenant_operation_action_logs
WHERE driver_id = :driver_id
ORDER BY log_date DESC
LIMIT 10;
```

Look for: `Index Scan` / `Bitmap Index Scan`, not `Seq Scan` on large tables.

## Caching recommendations

| Layer | TTL | When |
|-------|-----|------|
| Request memo (`request._mobile_dashboard_cache`) | Request lifetime | Always (tenant profile id) |
| Redis full dashboard | 0–30s | Summary polling only; `MOBILE_API_DASHBOARD_CACHE_TTL_SECONDS` |
| CDN / client | 30–60s | `dashboard/summary` endpoint; respect `generated_at` |
| Counter-only micro-cache | 10s | Future: if counters polled without full dashboard |

**Do not cache** across tenants or drivers. Include `tenant_schema` + `driver_id` in every key.

## Scalable mobile design

1. **Poll `/dashboard/summary/`** for counters + notifications + small activity cap.
2. **Load `/dashboard/`** once on cold start; refresh sections via slice endpoints (`recent-activity`, `notifications-summary`).
3. **Cap all lists** (activity 5–10, notification items 5–8).
4. **Avoid N+1** by never returning ORM models to serializers — only pre-projected dicts.
5. **Phase 2**: write-through inbox upsert with `dedupe_key` so operational hints persist without recomputing ephemeral rows every poll.

## Settings reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `MOBILE_API_DASHBOARD_FAST_SERIALIZE` | `true` | Skip nested DRF validation |
| `MOBILE_API_DASHBOARD_SUMMARY_SKIP_POD_ACTIVITY` | `true` | −1 query on summary poll |
| `MOBILE_API_DASHBOARD_CACHE_TTL_SECONDS` | `0` | Redis dashboard cache (off) |
| `MOBILE_API_DASHBOARD_SHIPMENT_SCOPE_PK_CAP` | `500` | Max PKs for POD `IN` clause |

## Deploy

```bash
python manage.py migrate tenant_workspace 0086
python manage.py migrate superadmin 0038
```

Apply on all tenant schemas for `0086`.
