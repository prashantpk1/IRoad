# Postman — Home Dashboard Module

## Import

1. **Collection:** `IRoad-Mobile-Driver-Dashboard.postman_collection.json`
2. **Environment:** `IRoad-Mobile-Driver-Dashboard.postman_environment.json`  
   (or use `IRoad-Mobile-Driver-APIs.postman_environment.json` from the main driver pack — dashboard variables were added there too.)

## Quick start

1. Select environment **IRoad Mobile Driver Dashboard — Local**.
2. Set `base_url` (e.g. `http://127.0.0.1:8000`).
3. Set `email` / `password` for a driver test user with `mobile.driver.dashboard`.
4. Run **Setup → Login**.
5. Run **Home Dashboard** requests or **Testing Flows → Flow A — Full Dashboard Smoke** (Collection Runner).

## API reference

| # | Name | Method | URL |
|---|------|--------|-----|
| 1 | Dashboard (full) | `GET` | `/api/v1/mobile/driver/dashboard/` |
| 2 | Dashboard summary | `GET` | `/api/v1/mobile/driver/dashboard/summary/` |
| 3 | Current job | *(embedded)* | Use request **03 — Get Current Job** → same as #1, tests `data.current_job` |
| 4 | Recent activity | `GET` | `/api/v1/mobile/driver/dashboard/recent-activity/?limit=1-10` |
| 5 | Notifications summary | `GET` | `/api/v1/mobile/driver/dashboard/notifications-summary/?variant=full\|summary` |
| 6 | Quick actions | *(embedded)* | Use request **06 — Get Quick Actions** → same as #1, tests `data.quick_actions` |

## Headers

| Header | Required | Notes |
|--------|----------|--------|
| `Authorization` | Yes | `Bearer {{access_token}}` |
| `Accept-Language` | No | `en` or `ar` (`{{accept_language}}`) |
| `X-Tenant-ID` | No | If set, must match JWT `tenant_schema` |
| `Content-Type` | — | Not used (GET only) |

## Environment variables

| Variable | Purpose |
|----------|---------|
| `base_url` | API origin (no trailing slash) |
| `access_token` | Set by Login |
| `refresh_token` | Set by Login |
| `email` / `password` | Login credentials |
| `accept_language` | `en` / `ar` |
| `dashboard_activity_limit` | Query `limit` for recent activity (1–10) |
| `dashboard_variant` | `full` or `summary` for notifications endpoint |
| `driver_id` | Saved from login |
| `current_job_shipment_id` | Saved from dashboard tests |
| `tenant_schema` | Saved from `welcome.operational_context` |

## Testing flows (Collection Runner)

| Flow | Purpose |
|------|---------|
| **Flow A — Full Dashboard Smoke** | Login → full dashboard → activity → notifications |
| **Flow B — Polling (summary)** | Summary dashboard + notifications `variant=summary` |
| **Flow C — Error cases** | No token (401), POST dashboard (405) — run manually |

## Related docs

- `mobile_api/docs/driver_dashboard.md`
- `mobile_api/docs/driver_dashboard_security.md`
- `mobile_api/docs/API_RESPONSE_CONTRACT.md`

## Main driver collection

`IRoad-Mobile-Driver-APIs.postman_collection.json` covers **auth and profile only** (no dashboard folder). Use this dashboard collection for all home-dashboard APIs.
