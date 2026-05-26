# Unified Job Detail API — Postman Setup Guide

Postman assets for **explicit driver job screens** and **paginated timelines** (not dashboard current-job selection).

## Files

| File | Purpose |
|------|---------|
| `Iroad_Mobile_Driver_Job_Detail.postman_collection.json` | Full collection (auth, live APIs, reference examples) |
| `Iroad_Mobile_Local.postman_environment.json` | Shared local environment (dashboard + job detail variables) |
| `Iroad_Mobile_Driver_Dashboard.postman_collection.json` | Optional — current-job dashboard |
| `JOB_DETAIL_SETUP.md` | This guide |
| `_generate_job_detail_collection.py` | Regenerate collection JSON after contract changes |

## Prerequisites

- Django API running: `python manage.py runserver` → `http://127.0.0.1:8000`
- A **driver** user with:
  - At least one **shipment** assigned to that driver (for shipment Job Detail)
  - Optionally an **empty move** assigned (for movement Job Detail)
- Redis if your settings require it for refresh tokens

## Import

1. Postman → **Import** → select:
   - `Iroad_Mobile_Driver_Job_Detail.postman_collection.json`
   - `Iroad_Mobile_Local.postman_environment.json`
2. Select environment **Iroad Mobile — Local** (top-right).
3. Edit `driver_email`, `driver_password`, and optionally `tenant_id`.

## Recommended run order

| Step | Request | Result |
|------|---------|--------|
| 1 | **01 — Auth & JWT → Driver Login** | Saves `access_token`, `refresh_token`, `tenant_schema`, `tenant_id`, `driver_id` |
| 2 | Set `shipment_id` | UUID or `shipment_no` from your tenant DB (or from login/dashboard) |
| 3 | **02 — Job Detail → Get Shipment Job Detail** | Full `job` / `workflow` / `timeline` preview / `pod_cod` / `round_trip` / `sync_metadata`; saves `job_detail_etag` |
| 4 | **02 → Get Shipment Job Detail (If-None-Match)** | **304** when unchanged |
| 5 | **03 — Timeline → Page 1** | Saves `timeline_cursor` |
| 6 | **03 — Timeline → Page 2** | Older events using cursor |
| 7 | Set `movement_id` | Empty-move UUID/no |
| 8 | **02 → Get Empty Move Job Detail** | `pod_cod` and `round_trip` are `{}` |
| 9 | **03 → Timeline — Empty Move** | Movement-scoped events |

## API endpoints

### Job Detail

```
GET {{base_url}}/driver/jobs/<job_type>/<job_id>/
```

| `job_type` | Aliases | Entity |
|------------|---------|--------|
| `shipment` | `shipments` | `TenantShipment` |
| `movement` | `movements`, `empty_move`, `empty-move` | `TenantTruckMovementLog` (empty move) |

**Response `data`:**

```json
{
  "job": {},
  "workflow": {},
  "timeline": {},
  "pod_cod": {},
  "round_trip": {},
  "alerts": {},
  "sync_metadata": {}
}
```

### Timeline pagination (dedicated)

```
GET {{base_url}}/driver/jobs/<job_type>/<job_id>/timeline/?limit=20&cursor=<token>
```

**Response `data`:**

```json
{
  "events": [],
  "next_cursor": "",
  "has_more": true
}
```

Timeline endpoint does **not** recompute workflow or POD/COD — Action Log keyset pages only.

## Headers

| Header | Required | Notes |
|--------|----------|-------|
| `Authorization` | Yes (live folders) | `Bearer {{access_token}}` |
| `Accept` | Recommended | `application/json` |
| `Accept-Language` | Optional | `en` / `ar` |
| `X-Request-ID` | Optional | `{{request_id}}` |
| `X-Tenant-ID` | Optional* | Must match JWT when sent |
| `If-None-Match` | Polling only | `{{job_detail_etag}}` on Job Detail GET |

## JWT flow

| Step | Endpoint |
|------|----------|
| Login | `POST /driver/auth/login/` |
| API calls | `Authorization: Bearer {{access_token}}` |
| Refresh | `POST /driver/auth/refresh/` |
| Logout | `POST /driver/auth/logout/` |

Login test script writes tokens to **environment** and **collection** variables.

## `sync_metadata` (Job Detail)

| Field | Purpose |
|-------|---------|
| `content_hash` | Stale detection / `meta.content_hash` |
| `workflow_version` | Workflow slice fingerprint |
| `entity_versions` | `booking`, `shipment`, `movement`, `action_log`, `pod_cod` |
| `generated_at` | Server timestamp (ISO 8601) |
| `job_detail_projection_version` | Contract version (`"1"`) |
| `workflow_integrity` | Log-primary reconcile flags |
| `compliance_integrity` | POD/COD drift |
| `job_etag` | Mirrors response `ETag` header |

## Security tests (live folder 02)

| Request | Expected |
|---------|----------|
| No Authorization | **401** |
| Wrong `X-Tenant-ID` | **403** `tenant_mismatch` |
| Foreign `shipment_id` | **403** `forbidden` |
| Unknown UUID | **404** `job_not_found` |

## Reference examples (folder 04)

Open any `[Example] …` request → **Examples** (right panel) — no server required.

| Example | Illustrates |
|---------|-------------|
| Shipment — One-Way | Full contract + POD pending |
| Round Trip | `OUTBOUND_COMPLETED`, backload active |
| Split Driver | `progression_mode: split_driver` |
| Empty Move | Movement job; empty `pod_cod` |
| POD Compliant / Hard POD / COD | Compliance slices |
| Sync Metadata | `entity_versions`, ETag |
| Timeline Page | `events`, `next_cursor`, `has_more` |
| 401 / 403 / Tenant | Error envelopes |

## RBAC

Capability: **`mobile.driver.job_detail`** (driver JWT with `driver_id` claim).

## Troubleshooting

| Symptom | Check |
|---------|--------|
| 401 | Run **Driver Login**; verify Bearer token |
| 403 forbidden | `shipment_id` must be assigned to logged-in driver |
| 403 tenant_mismatch | Remove or fix `X-Tenant-ID` |
| 404 | Valid UUID / `shipment_no` in tenant schema |
| Empty `events` | Job has no Action Logs yet |
| 400 timeline cursor | Re-run **Timeline Page 1** to refresh `timeline_cursor` |

## Related

- `README.md` — dashboard collection
- `mobile_api/docs/API_RESPONSE_CONTRACT.md` — envelope format
