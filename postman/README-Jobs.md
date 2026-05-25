# Postman — Job List Module

## Import

| File | Purpose |
|------|---------|
| `IRoad-Mobile-Driver-Jobs.postman_collection.json` | All job list APIs + flows |
| `IRoad-Mobile-Driver-Jobs.postman_environment.json` | Local variables |

You can also reuse `IRoad-Mobile-Driver-APIs.postman_environment.json` if `access_token` is already set from the main driver pack.

## Quick start

1. Select environment **IRoad Mobile Driver Jobs — Local**.
2. Set `base_url` (e.g. `http://127.0.0.1:8000` or your Cloudflare tunnel URL).
3. Set `email` / `password` for a driver user with capability **`mobile.driver.jobs`**.
4. Run **Setup → Login**.
5. Run **Testing Flows → Flow A — Full Job List Smoke** (Collection Runner).

Regenerate collection after API changes:

```bash
python postman/generate_jobs_postman.py
```

## API map

| # | Request | Method | Path |
|---|---------|--------|------|
| — | Job summary | `GET` | `/api/v1/mobile/driver/jobs/summary/` |
| 1 | Shipments (all) | `GET` | `/api/v1/mobile/driver/jobs/shipments/` |
| 2 | Shipments active | `GET` | `/api/v1/mobile/driver/jobs/shipments/active/` |
| 3 | Shipments completed | `GET` | `/api/v1/mobile/driver/jobs/shipments/completed/` |
| 4 | Shipments cancelled | `GET` | `/api/v1/mobile/driver/jobs/shipments/cancelled/` |
| 5 | Shipments POD pending | `GET` | `/api/v1/mobile/driver/jobs/shipments/pod-pending/` |
| 6 | Shipments COD pending | `GET` | `/api/v1/mobile/driver/jobs/shipments/cod-pending/` |
| 7 | Movements (all) | `GET` | `/api/v1/mobile/driver/jobs/movements/` |
| 8 | Movements active | `GET` | `/api/v1/mobile/driver/jobs/movements/active/` |
| 9 | Movements completed | `GET` | `/api/v1/mobile/driver/jobs/movements/completed/` |
| 10 | Movements cancelled | `GET` | `/api/v1/mobile/driver/jobs/movements/cancelled/` |
| 11 | Movements empty | `GET` | `/api/v1/mobile/driver/jobs/movements/empty/` |

## Headers

| Header | Required | Notes |
|--------|----------|--------|
| `Authorization` | Yes | `Bearer {{access_token}}` (collection auth + per-request) |
| `Accept-Language` | No | `{{accept_language}}` — `en` / `ar` |
| `X-Tenant-ID` | No | If set, must match JWT `tenant_schema` |

## JWT automation

- **Login** saves `access_token`, `refresh_token`, `driver_id`.
- Collection **Bearer** auth uses `{{access_token}}`.
- Pre-request script warns if token is empty on non-login calls.

## Pagination examples (folder **03 — Examples**)

```
?page=1&page_size=10
?page=2&page_size=5
?include_total=0          # skip COUNT(*)
?include_actions=0        # skip latest-action batch
```

## Search examples

```
?q=SH-100                 # shipment_no prefix (min 2 chars)
?search=SH-100            # alias for q
?q=MV-22                  # movement_no or linked shipment_no
```

## Filter examples

```
?tab=active&queue=none&sort=updated_desc
?sort=priority_desc       # POD/COD first (shipments)
?date_from=2026-05-01&date_to=2026-05-31&date_field=updated
?date_field=operational   # shipment_date / movement_date
```

Path routes **lock** `tab` or `queue` — query cannot override (see `meta.tab_locked`).

## Error & RBAC samples (folder **04**)

| Case | Expected |
|------|----------|
| No Bearer | **401** `mobile.auth.unauthorized` |
| Wrong `X-Tenant-ID` | **403** `tenant_mismatch` |
| POST on list URL | **405** `jobs_method_not_allowed` |
| Non-driver JWT | **403** `mobile.auth.jobs_denied` |

## Testing flows

| Flow | Purpose |
|------|---------|
| **Flow A** | Login → summary → active/POD shipments → active/empty movements |
| **Flow B** | All locked tab routes |
| **Flow C** | Pagination + search |
| **Flow D** | Manual errors (no token, POST) |

## Environment variables

| Variable | Purpose |
|----------|---------|
| `base_url` | API origin |
| `access_token` / `refresh_token` | JWT (Login) |
| `email` / `password` | Credentials |
| `tenant_id` | Optional `X-Tenant-ID` |
| `jobs_page_size` / `jobs_page` | Pagination |
| `jobs_search_shipment` / `jobs_search_movement` | Search terms |
| `jobs_date_from` / `jobs_date_to` | Date filters |
| `jobs_sort` | `updated_desc`, `priority_desc`, etc. |
| `last_job_id` | Set by list tests from first card |

## Related docs

- `mobile_api/docs/driver_job_list.md`
- `mobile_api/docs/driver_job_list_summary.md`
- `mobile_api/docs/driver_job_list_pagination.md`
- `mobile_api/docs/driver_job_list_security.md`
- `mobile_api/docs/driver_job_list_performance.md`
