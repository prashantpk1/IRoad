# Iroad Mobile API — Postman

Postman assets for the **Unified Driver Dashboard**, **Job Detail**, **Execute Action**, **POD Capture**, and **Ops Staging** APIs.

## Files

| File | Purpose |
|------|---------|
| `Iroad_Mobile_Driver_Ops_Staging.postman_collection.json` | **Hard POD + Payment + Issues** — bearer-only (no login) |
| `Iroad_Mobile_Ops_Staging.postman_environment.json` | Ops staging environment (`bearer_token`, `tenant_header`, idempotency keys) |
| `OPS_STAGING_SETUP.md` | Hard POD / Payment / Issues setup guide |
| `OPS_STAGING_SAMPLE_PAYLOADS.md` | Ops staging request/response samples |
| `Iroad_Mobile_Driver_POD_Capture.postman_collection.json` | **POD Capture** — 14 scenarios + execute promotion, bearer-only |
| `Iroad_Mobile_POD_Capture.postman_environment.json` | POD Capture environment (`bearer_token`, `tenant_header`, bundle ids) |
| `POD_CAPTURE_SETUP.md` | POD Capture setup guide |
| `POD_CAPTURE_SAMPLE_PAYLOADS.md` | POD request/response samples |
| `Iroad_Mobile_Driver_Execute_Action.postman_collection.json` | **Execute Action** — 12 scenarios, bearer-only (no login) |
| `Iroad_Mobile_Driver_Job_Detail.postman_collection.json` | **Job Detail** — auth, job GET, timeline pagination, examples |
| `Iroad_Mobile_Driver_Dashboard.postman_collection.json` | **Dashboard** — current job, ETag polling, examples |
| `Iroad_Mobile_Local.postman_environment.json` | Shared local environment (auth + dashboard + job detail + execute vars) |
| `EXECUTE_ACTION_SETUP.md` | Execute Action setup guide |
| `EXECUTE_ACTION_SAMPLE_PAYLOADS.md` | Execute request body reference |
| `JOB_DETAIL_SETUP.md` | Job Detail setup guide (recommended starting point) |
| `README.md` | This file (index) |

### Quick start — POD Capture

1. Import `Iroad_Mobile_Driver_POD_Capture.postman_collection.json` + `Iroad_Mobile_POD_Capture.postman_environment.json`.
2. Paste driver JWT into `bearer_token`; set `tenant_header`, `driver_id`, `shipment_id`.
3. Run **00 → GET Shipment Job Detail** (sync hashes).
4. Run **01 → 1. POD image capture** → copy `capture_bundle_id`.
5. Run **03 → 14. Execute — promote staged bundle**.

See `POD_CAPTURE_SETUP.md` for all 14 scenarios.

### Quick start — Ops Staging (Hard POD / Payment / Issues)

1. Import `Iroad_Mobile_Driver_Ops_Staging.postman_collection.json` + `Iroad_Mobile_Ops_Staging.postman_environment.json`.
2. Paste driver JWT into `bearer_token`; set `tenant_header`, `driver_id`, `shipment_id`.
3. Run **01 → Hard POD list**, then **02 → submit**, **03 → payment**, **04 → issues**.
4. Run **04 → 5. Job Detail** to verify `operational_issues` visibility.

See `OPS_STAGING_SETUP.md` for full run order.

### Quick start — Execute Action

1. Import `Iroad_Mobile_Driver_Execute_Action.postman_collection.json` + environment.
2. Paste driver JWT into `bearer_token` (or set `access_token` from Job Detail login).
3. Set `tenant_schema`, `shipment_id`.
4. Run Job Detail GET (separate collection) to copy sync fields.
5. Run **01 — Execute** folder (then **02** negatives).

See `EXECUTE_ACTION_SETUP.md` for full run order.

### Quick start — Job Detail

1. Import collection + environment (see `JOB_DETAIL_SETUP.md`).
2. Run **01 — Auth & JWT → Driver Login**.
3. Set `shipment_id`, then **02 — Get Shipment Job Detail**.
4. Run **03 — Timeline — Page 1**, then **Page 2** with saved cursor.

---

## Dashboard (Unified Driver Dashboard)

Obtain a driver JWT via login (included in Job Detail collection folder **01**) or set **`access_token`** manually.

## Files (dashboard)

| File | Purpose |
|------|---------|
| `Iroad_Mobile_Driver_Dashboard.postman_collection.json` | Collection (**02** live dashboard, **03** saved example responses only) |
| `Iroad_Mobile_Local.postman_environment.json` | Local environment variables |

## Prerequisites

- Django API running (e.g. `python manage.py runserver` → `http://127.0.0.1:8000`)
- A **driver** user in a tenant schema with at least one **Confirmed** booking assigned (for non-empty dashboard)
- Redis configured if your settings require it for refresh tokens (production-like setups)

## Import into Postman

1. Open Postman → **Import** → drag both JSON files (or import folder `mobile_api/postman/`).
2. Select environment **Iroad Mobile — Local** in the top-right dropdown.
3. Edit environment values:
   - `base_url` — default `http://127.0.0.1:8000/api/v1/mobile`
   - `driver_email` / `driver_password` — your test driver credentials
   - `tenant_id` — only if login requires explicit tenant (multi-tenant same email)

## Recommended run order

1. Obtain **`access_token`** (driver login against `POST {{base_url}}/driver/auth/login/` or reuse a token from another collection).
2. Set **`access_token`** in environment or collection **Authorization → Bearer Token**.
3. Run **02 — Driver Dashboard (Live) → Get Dashboard** (saves `dashboard_etag` and `dashboard_content_hash` from the response).
4. Run **Get Dashboard (If-None-Match — expect 304)** to verify polling (expect **304** if nothing changed since step 3).

## JWT token flow

| Step | Endpoint | Result |
|------|----------|--------|
| 1 | `POST /driver/auth/login/` | Returns `access_token` + `refresh_token` |
| 2 | Use `Authorization: Bearer {{access_token}}` on dashboard | Authenticated calls |
| 3 | `POST /driver/auth/refresh/` | Rotates tokens when access JWT expires |
| 4 | `POST /driver/auth/logout/` | Optional — invalidates refresh |

This dashboard-only collection does not include login requests; paste or set tokens manually.

## Dashboard API

**`GET {{base_url}}/driver/dashboard/`**

### Headers (authenticated)

| Header | Required | Example |
|--------|----------|---------|
| `Authorization` | Yes | `Bearer {{access_token}}` |
| `Accept` | Recommended | `application/json` |
| `Accept-Language` | Optional | `en` or `ar` |
| `X-Request-ID` | Optional | `postman-{{$guid}}` |
| `X-Tenant-ID` | Optional* | `{{tenant_id}}` (must match JWT when sent) |

\*JWT `tenant_schema` is enough for tenant isolation; mobile apps may omit `X-Tenant-ID`.

### Response `data` (contract)

```json
{
  "current_job": {},
  "current_empty_move": {},
  "workflow": {},
  "pod_cod_summary": {},
  "timeline_summary": {},
  "alerts": {},
  "sync_metadata": {}
}
```

### Polling (`ETag` / `304`)

| Step | Request | Result |
|------|---------|--------|
| 1 | **Get Dashboard** | **200** + JSON body; response header **`ETag`** saved to `{{dashboard_etag}}` |
| 2 | **Get Dashboard (If-None-Match)** | **304** empty body when unchanged; **`ETag`** header echoed |

Mobile clients should send `If-None-Match` on repeat polls (e.g. every 5s) and skip parsing when **304**.

### `sync_metadata` v2 (offline / replay)

| Field | Purpose |
|-------|---------|
| `dashboard_projection_version` | `"2"` — API contract version |
| `last_action_log_id` | Latest Action Log id for active scope |
| `content_hash` | Stale-dashboard detection |
| `workflow_version` | Workflow slice version |
| `server_time` | Server clock reference |
| `entity_versions` | Per-entity version tokens (`booking`, `shipment`, `movement`, `action_log`, `pod_cod`) |
| `workflow_integrity` | `authority_source`, `missing_log_warning`, `fallback_to_columns`, etc. |
| `compliance_integrity` | POD/COD/treasury reconcile flags (also under `pod_cod_summary`) |
| `dashboard_etag` | Same value as response `ETag` header (when 200) |

`current_job` may include `booking_execution_stage`, `execution_progress_percentage`, `business_progress_percentage` for round-trip lifecycle.

## Tenant header examples

| Scenario | `X-Tenant-ID` | Expected |
|----------|---------------|----------|
| Bearer only (recommended) | Omitted | 200 when session valid |
| Matching tenant hint | Same as JWT `tenant_schema` / org `tenant_id` | 200 |
| Wrong tenant | `wrong-tenant-schema` | 403 `tenant_mismatch` |

Collection folder **02 — Driver Dashboard** includes:

- **Get Dashboard** — with `X-Tenant-ID`; tests + saves ETag
- **Get Dashboard (Bearer only)** — without header
- **Get Dashboard (If-None-Match — expect 304)** — polling
- **Get Dashboard — Tenant mismatch** — negative test

## Saved example responses (no server required)

Folder **03 — Dashboard Examples (Reference)** contains saved bodies for:

| Example | Illustrates |
|---------|-------------|
| Active Job (One-Way) | `sync_metadata` v2, `workflow_integrity`, ETag header |
| Round Trip | `OUTBOUND_COMPLETED` → backload, execution progress |
| 304 Not Modified | Polling — empty body |
| Empty Move + Job | Job + empty move + timeline |
| Empty State | Idle driver; `missing_log_warning` example |
| POD/COD — Drift | `compliance_integrity.compliance_drift` |

Open a request → **Examples** (right panel) → pick a saved response. For live **401** / **403** behaviour, call folder **02** without a token, with a bad token, or with a mismatched `X-Tenant-ID`.

## Security & RBAC

- Dashboard requires driver JWT + capability **`mobile.driver.dashboard`**.

## Related docs

- `mobile_api/docs/API_RESPONSE_CONTRACT.md` — envelope (`status`, `meta`, errors)
- `mobile_api/docs/mobile_rbac.md` — capabilities
- `mobile_api/docs/MOBILE_AUTH_ENV_REQUIRED.md` — production JWT/Redis settings

## Troubleshooting

| Symptom | Check |
|---------|--------|
| 401 on dashboard | Set a valid **`access_token`** (login outside this collection); verify Bearer on the request |
| 403 tenant_mismatch | Align `X-Tenant-ID` with login `organization.tenant_id` or remove header |
| Empty `current_job` | Driver has no active Confirmed booking / all shipments CLOSED |
| 429 on login | Login throttle — wait or adjust `MOBILE_API_LOGIN_BURST_*` in settings |
