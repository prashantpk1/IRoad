# Driver job list — production hardening

Operational guide for go-live: cache, guards, observability, and large-tenant validation.

## Cache architecture

| Slice | Key pattern | Default TTL | Notes |
|-------|-------------|-------------|-------|
| Summary | `mobile:jobs:v1:summary:{schema}:{driver_id}` | 30s | `GET /jobs/summary/` — two aggregate queries |
| List page | `mobile:jobs:v1:list:{schema}:{driver_id}:{fingerprint}` | 0 (off) | Optional; SHA-256 of filters + page |

- Fail-open on Redis/cache errors (same pattern as dashboard).
- Invalidate summary: `invalidate_driver_job_list_cache(tenant_schema, driver_id)` after operational writes.
- Mobile clients should use **`include_total=0`** on list polls to skip `COUNT(*)`.

## Production settings

| Setting | Default | Purpose |
|---------|---------|---------|
| `MOBILE_API_JOBS_SUMMARY_CACHE_TTL_SECONDS` | 30 | Summary badge cache |
| `MOBILE_API_JOBS_LIST_CACHE_TTL_SECONDS` | 0 | List page cache (enable only for locked-tab polls) |
| `MOBILE_API_JOBS_UNION_DRIVER_SCOPE` | true | UNION pk scope (no OR join on list plan) |
| `MOBILE_API_JOBS_DEFAULT_PAGINATION` | cursor | Keyset default; use `page=` for offset legacy |
| `MOBILE_API_JOBS_COUNT_CACHE_TTL_SECONDS` | 60 | COUNT cache when `include_total=1` |
| `MOBILE_API_JOBS_ENFORCE_PAYLOAD_LIMIT` | true | Hard payload cap + truncation |
| `MOBILE_API_JOBS_MAX_PAGE_SIZE` | 50 | Cap `page_size` |
| `MOBILE_API_JOBS_MAX_PAGE` | 500 | Max page number (offset mode) |
| `MOBILE_API_JOBS_MAX_OFFSET_ROWS` | 5000 | Deep-pagination guard |
| `MOBILE_API_JOBS_MAX_RESPONSE_BYTES` | 524288 | Payload byte cap |
| `MOBILE_API_JOBS_SLOW_REQUEST_MS` | 1200 | Slow request log + audit |
| `MOBILE_API_JOBS_METRICS_ENABLED` | true | Security audit on slow ops |
| `MOBILE_API_JOBS_DISALLOW_TAB_ALL` | true | Blocks unbounded `tab=all` |
| REST `mobile_jobs` throttle | 90/min | Per authenticated driver |

List toggles: `MOBILE_JOB_LIST_PAGE_ACTION_BATCH`, `MOBILE_JOB_LIST_FAST_SERIALIZE`, `MOBILE_JOB_LIST_INCLUDE_TOTAL_DEFAULT` (**false** — polling must not COUNT by default).

## Query hardening

- Driver-scoped base querysets only (`job_list_security`).
- Search: min 2 chars, max 64, prefix/exact on indexed `shipment_no` / `movement_no`.
- Movement shipment lookup: bounded subquery (200 ids), no join OR chains.
- Date span capped at 366 days (`job_list_dates`).
- Post-pagination action batch (`DISTINCT ON`) — not correlated subquery on full filter set.

## Pagination safeguards

- `MobileJobListPagination` rejects offset ≥ `MOBILE_API_JOBS_MAX_OFFSET_ROWS`.
- `include_total=0` skips COUNT for infinite-scroll UIs.

## Rate limiting

- All job routes use `MobileJobListThrottle` (`mobile_jobs` scope).
- Middleware: read-only GET, optional `X-Tenant-ID` vs JWT tenant binding.

## Observability

Logger: `mobile_api.jobs`

| Event | Level | When |
|-------|-------|------|
| `jobs.{operation}` | info / warning | Per list page, summary, paginate, count |
| `jobs.payload_oversize` | warning | Serialized items exceed byte cap |
| `jobs.middleware slow_request` | warning | End-to-end path ≥ slow threshold |
| `job_list_slow_request` | audit | Metrics enabled + slow threshold |

Operations: `list_page`, `summary`, `summary_build`, `paginate`, `count`.

## Monitoring hooks

1. **Logs** — filter `mobile_api.jobs` for `ms=` and `slow_request`.
2. **Audit** — `job_list_slow_request`, `jobs_middleware_tenant_mismatch`, `job_list_ownership_violation`.
3. **Deploy checks** — `python manage.py check --deploy` (E041 capability, W060 indexes).
4. **Readiness** — `python manage.py verify_job_list_readiness --schema=<tenant>`.

## Scalability validation (large tenants)

| Scenario | Target | How to verify |
|----------|--------|----------------|
| Active shipment list (page 10) | ≤ 4 DB round-trips | `include_total=0`, `include_actions=1`, EXPLAIN on driver+status index |
| Summary counters | ≤ 2 aggregates | Cache hit on repeat within TTL |
| Movement search by shipment_no | Subquery cap 200 | No seq scan on movement table |
| Deep page 501 | 400 `job_list_pagination_limit` | Integration test / Postman |
| Mobile latency p95 | < 1.2s warm | Load test with `MOBILE_API_JOBS_SUMMARY_CACHE_TTL_SECONDS=30` |

Recommended production client params:

```
page_size=20&include_actions=1
```

Second page (cursor):

```
page_size=20&cursor=<next_cursor from prior response>
```

Optional total count (cached server-side):

```
include_total=1
```

Locked routes (`/shipments/active/`, `/pod-pending/`, etc.) avoid unbounded `tab=all`.

## Migrations required

Tenant: `0088_job_list_search_indexes`, `0089_job_list_movement_action_log_index`.

## Related docs

- [driver_job_list_performance.md](./driver_job_list_performance.md)
- [driver_job_list_security.md](./driver_job_list_security.md)
