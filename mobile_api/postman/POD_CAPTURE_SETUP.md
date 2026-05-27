# POD Capture API — Postman Setup Guide

Postman assets for **POD evidence capture** and **Execute bundle promotion**.

**No login APIs** in this collection — supply a driver JWT via `{{bearer_token}}`.

## Files

| File | Purpose |
|------|---------|
| `Iroad_Mobile_Driver_POD_Capture.postman_collection.json` | All 14 scenarios (capture + execute promotion) |
| `Iroad_Mobile_POD_Capture.postman_environment.json` | POD-specific environment variables |
| `Iroad_Mobile_Local.postman_environment.json` | Shared local env (optional — merge POD vars) |
| `POD_CAPTURE_SETUP.md` | This guide |
| `POD_CAPTURE_SAMPLE_PAYLOADS.md` | Request/response body reference |
| `_generate_pod_capture_collection.py` | Regenerate collection after contract changes |

## API endpoints

| Step | Method | Path |
|------|--------|------|
| Sync (optional) | `GET` | `/driver/jobs/shipment/{{shipment_id}}/` |
| POD Capture | `POST` | `/driver/jobs/shipments/{{shipment_id}}/pod/capture/` |
| Execute + promote | `POST` | `/driver/jobs/shipment/{{shipment_id}}/actions/{{execute_pod_action_code}}/execute/` |

Base: `{{base_url}}` → `http://127.0.0.1:8000/api/v1/mobile`

## Prerequisites

- Django: `python manage.py runserver`
- Driver JWT with capabilities:
  - `mobile.driver.pod_capture` (capture)
  - `mobile.driver.execute` (promotion)
- Assigned **shipment** in tenant schema
- Upload files to storage paths under:

  `mobile_driver_uploads/{{tenant_schema}}/{{driver_id}}/{{shipment_id}}/pod_capture/`

  (or rely on `MOBILE_API_POD_CAPTURE_VERIFY_STORAGE=false` in dev)

## Import

1. Postman → **Import**:
   - `Iroad_Mobile_Driver_POD_Capture.postman_collection.json`
   - `Iroad_Mobile_POD_Capture.postman_environment.json`
2. Select environment **Iroad Mobile — POD Capture (Local)**.
3. Set required variables (below).

## Required variables

| Variable | Example | Notes |
|----------|---------|--------|
| `bearer_token` | `eyJ...` | Driver access JWT |
| `tenant_header` | `tenant_acme` | `X-Tenant-ID` — must match JWT |
| `tenant_schema` | `tenant_acme` | Synced to `tenant_header` by collection |
| `driver_id` | UUID | JWT `driver_id` — used in upload paths |
| `shipment_id` | UUID or `SHP-001` | Driver-owned shipment |
| `pod_content_hash` | from Job Detail | Stale-sync for capture/execute |
| `pod_workflow_version` | from Job Detail | Stale-sync |
| `execute_pod_action_code` | `POD_CAP` or `A7` | POD Action Master row |

### Bearer token

Paste into **`bearer_token`**. If you use **`access_token`** from another collection, the pre-request script copies it when `bearer_token` is empty.

### Tenant header

Every request sends:

```http
X-Tenant-ID: {{tenant_header}}
Authorization: Bearer {{bearer_token}}
```

Recommended: set `tenant_schema` and `tenant_header` to the same value as JWT `tenant_schema`.

## Recommended run order

| # | Folder / request | Expected |
|---|------------------|----------|
| — | Set `bearer_token`, `tenant_header`, `driver_id`, `shipment_id` | — |
| 0 | **00 → GET Shipment Job Detail** | `200` — saves sync hashes |
| 1 | **01 → 1. POD image capture** | `201` — saves `capture_bundle_id` |
| 6 | **01 → 6. Replay-safe capture** | `200`, `replayed: true` |
| 2–5 | Other POD types (video, signature, hard, multi-page) | `201` each (new `client_capture_id`) |
| 14 | **03 → 14. Execute — promote staged bundle** | `201`, `data.pod_capture` |
| 14b | **03 → 14b. Execute idempotent replay** | `200`, `reused_existing` |
| 7–13 | **02** negative tests | `4xx` |
| 14c | **03 → 14c. Duplicate promotion** | `409` `bundle_already_promoted` |
| 14d | **03 → 10/14d. Expired bundle** | `410` (set `expired_bundle_id`) |

## Scenario index (collection)

| # | Scenario | Folder |
|---|----------|--------|
| 1 | POD image capture | 01 |
| 2 | POD video capture | 01 |
| 3 | Signature POD | 01 |
| 4 | Hard POD | 01 |
| 5 | Multi-page POD | 01 |
| 6 | Replay-safe capture | 01 |
| 7 | Wrong shipment | 02 |
| 8 | Wrong driver | 02 |
| 9 | Wrong tenant | 02 |
| 10 | Expired bundle | 03 → 14d |
| 11 | Invalid MIME | 02 |
| 12 | Missing GPS | 02 |
| 13 | Invalid POD type | 02 |
| 14 | Execute promotion | 03 |

## RBAC

| API | Capability |
|-----|------------|
| POD Capture | `mobile.driver.pod_capture` |
| Execute promotion | `mobile.driver.execute` |

## Expired bundle test (10 / 14d)

1. Run capture to create a bundle.
2. Wait until bundle TTL expires (see `POD_CAPTURE_BUNDLE_TTL` / settings), **or**
3. Copy `capture_bundle_id` into `expired_bundle_id` from an already-expired bundle in your environment.
4. Run **14d. Execute — expired bundle**.

## Regenerate collection

```bash
python mobile_api/postman/_generate_pod_capture_collection.py
```

## Troubleshooting

| Symptom | Check |
|---------|--------|
| 401 | Valid `bearer_token` on collection auth |
| 403 `tenant_mismatch` | Align `tenant_header` with JWT |
| 403 `orphan_upload` | `file_ref` must include correct tenant/driver/shipment segments |
| 400 `gps_required` | Set `pod_latitude` / `pod_longitude` or use action without GPS |
| 404 `target_action_not_found` | Configure POD Action Master row / `execute_pod_action_code` |
| 409 `bundle_already_promoted` | Expected for duplicate promotion test |
| Execute missing `pod_capture` | Body must include `capture_bundle_id`; run capture first |

## Related

- `EXECUTE_ACTION_SETUP.md` — general execute flow
- `JOB_DETAIL_SETUP.md` — sync metadata source
