# Unified Execute Action API — Postman Setup Guide

Postman assets for **driver workflow execution** (`POST .../actions/<action_code>/execute/`).

**No login APIs** in this collection — supply a JWT via `{{bearer_token}}`.

## Files

| File | Purpose |
|------|---------|
| `Iroad_Mobile_Driver_Execute_Action.postman_collection.json` | All 12 execute scenarios + Job Detail sync helpers |
| `Iroad_Mobile_Local.postman_environment.json` | Shared environment (`bearer_token`, tenant, job IDs, sync fields) |
| `EXECUTE_ACTION_SETUP.md` | This guide |
| `EXECUTE_ACTION_SAMPLE_PAYLOADS.md` | Copy-paste request bodies per scenario |
| `_generate_execute_action_collection.py` | Regenerate collection after contract changes |

## Prerequisites

- Django API: `python manage.py runserver` → `http://127.0.0.1:8000`
- A **driver JWT** with capability `mobile.driver.execute`
- Assigned **shipment** (and optionally **empty move**) in the tenant schema
- For POD/COD/Hard POD: jobs where `pod_cod` flags are pending in Job Detail

## Import

1. Postman → **Import**:
   - `Iroad_Mobile_Driver_Execute_Action.postman_collection.json`
   - `Iroad_Mobile_Local.postman_environment.json` (if not already imported)
2. Select environment **Iroad Mobile — Local**.
3. Set variables (see below).

## Required environment variables

| Variable | Example | Notes |
|----------|---------|--------|
| `base_url` | `http://127.0.0.1:8000/api/v1/mobile` | Must include `/api/v1/mobile` |
| `bearer_token` | `eyJ...` | Driver access JWT (paste manually) |
| `tenant_schema` | `tenant_acme` | Sent as `X-Tenant-ID`; must match JWT |
| `shipment_id` | UUID or `shipment_no` | Driver-owned shipment |
| `movement_id` | UUID or `movement_no` | Driver-owned empty move |

Optional (auto-filled by **00 — Sync** or successful executes):

| Variable | Purpose |
|----------|---------|
| `execute_content_hash` | From Job Detail / execute response `sync_metadata` |
| `execute_workflow_version` | Stale-sync guard |
| `execute_action_code` | Primary workflow action |
| `execute_pod_action_code` | POD capture action |
| `execute_cod_action_code` | COD collection action |
| `execute_hard_pod_action_code` | Hard POD action |
| `execute_evidence_action_code` | Action with GPS/photo requirements (negative test #12) |
| `execute_replay_client_action_id` | Saved after first `201` for replay test |

Negative-test defaults:

| Variable | Purpose |
|----------|---------|
| `wrong_tenant_id` | `X-Tenant-ID` mismatch (test #8) |
| `foreign_shipment_id` | Job not owned by driver (test #9) |
| `invalid_action_code` | `ZZZ_NOT_ALLOWED` (test #11) |
| `stale_content_hash` / `stale_workflow_version` | Intentionally wrong sync (test #7) |

### Bearer token

Obtain a driver access token outside this collection (mobile app, curl, or the Job Detail collection login folder) and paste into **`bearer_token`**.

If you already use **`access_token`** from Job Detail login, the collection pre-request script copies it to `bearer_token` when `bearer_token` is empty.

## Recommended run order

| Step | Request | Expected |
|------|---------|----------|
| 1 | Set `bearer_token`, `tenant_schema`, `shipment_id` | — |
| 2 | **Job Detail GET** (separate collection) | Copy `execute_content_hash`, `execute_workflow_version`, action codes |
| 3 | **01 → 1. Shipment Execute** | `201` |
| 4 | **01 → 6. Idempotent Replay** | `200`, `reused_existing: true` |
| 5 | Set `movement_id` → **00 → Get Empty Move Job Detail** | `200` |
| 6 | **01 → 2. Empty Move Execute** | `201` |
| 7 | When `pod_cod.pod_pending` → set `execute_pod_action_code` → **3. POD Execute** | `201` |
| 8 | When `cod_pending` → **4. COD Execute** | `201` |
| 9 | When `hard_pod_pending` → **5. Hard POD Execute** | `201` |
| 10 | **02 → 7–12** negative tests | See folder descriptions |

## API endpoint

```
POST {{base_url}}/driver/jobs/<job_type>/<job_id>/actions/<action_code>/execute/
```

| `job_type` | Entity |
|------------|--------|
| `shipment` | Assigned shipment |
| `movement` | Empty move / truck movement log |

### Request body

```json
{
  "client_action_id": "<uuid-per-attempt>",
  "workflow_version": "<from sync_metadata>",
  "content_hash": "<from sync_metadata>",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "notes": "",
  "media": []
}
```

### Response `data`

```json
{
  "execution": {},
  "workflow": {},
  "pod_cod": {},
  "timeline_preview": {},
  "sync_metadata": {},
  "alerts": {}
}
```

## Headers

| Header | Required | Value |
|--------|----------|--------|
| `Authorization` | Yes | `Bearer {{bearer_token}}` |
| `Content-Type` | Yes | `application/json` |
| `X-Tenant-ID` | Recommended | `{{tenant_schema}}` |
| `X-Request-ID` | Optional | `postman-{{$guid}}` |

## Security & RBAC

| Check | Enforcement |
|-------|-------------|
| JWT | `IsMobileAuthenticated` |
| Driver role | `IsDriver` + `driver_id` claim |
| Capability | `mobile.driver.execute` |
| Tenant | `schema_context` + `X-Tenant-ID` alignment |
| Ownership | Job must belong to authenticated driver |
| Stale sync | `content_hash` / `workflow_version` vs server |
| Idempotency | `client_action_id` required |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| 401 Unauthorized | Refresh `bearer_token` |
| 400 `tenant_required` | Set `tenant_schema` / `X-Tenant-ID` |
| 403 `tenant_mismatch` | Align `X-Tenant-ID` with JWT `tenant_schema` |
| 403 `forbidden` on foreign job | Use driver's own `shipment_id` |
| 409 stale | Re-run Job Detail GET; copy fresh `execute_content_hash` |
| 400 `action_not_allowed` | Pick `action_code` from `workflow.allowed_actions` |
| 400 `gps_required` / `photo_required` | Add coordinates/media or use test #12 action only for negative test |
| POD/COD requests skip | Set `execute_pod_action_code` / `execute_cod_action_code` manually |

## Related

- `EXECUTE_ACTION_SAMPLE_PAYLOADS.md` — bodies for all 12 scenarios
- `Iroad_Mobile_Driver_Job_Detail.postman_collection.json` — Job Detail GET + timeline
- `mobile_api/execution/` — server implementation
