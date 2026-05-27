# Ops Staging APIs — Postman Setup Guide

Postman assets for **Hard POD**, **Payment Collection**, and **Delay / Issue Reporting**.

**No login APIs** in this collection — supply a driver JWT via `{{bearer_token}}`.

## Files

| File | Purpose |
|------|---------|
| `Iroad_Mobile_Driver_Ops_Staging.postman_collection.json` | All scenarios (list, submit, payment, issues) |
| `Iroad_Mobile_Ops_Staging.postman_environment.json` | Environment variables |
| `OPS_STAGING_SETUP.md` | This guide |
| `OPS_STAGING_SAMPLE_PAYLOADS.md` | Request/response body reference |
| `_generate_ops_staging_collection.py` | Regenerate collection after contract changes |

## API endpoints

| API | Method | Path |
|-----|--------|------|
| Hard POD List | `GET` | `/driver/hard-pod/pending/` |
| Hard POD Submit | `POST` | `/driver/hard-pod/submit/` |
| Payment Collection | `POST` | `/driver/payments/collect/` |
| Issue Reporting | `POST` | `/driver/issues/report/` |
| Job Detail (issues visibility) | `GET` | `/driver/jobs/shipment/{{shipment_id}}/` |

Base: `{{base_url}}` → `http://127.0.0.1:8000/api/v1/mobile`

## Prerequisites

- Django: `python manage.py runserver`
- Driver JWT with capabilities:
  - `mobile.driver.hard_pod` (Hard POD)
  - `mobile.driver.payment_collection` (payments)
  - `mobile.driver.issues` (issue reporting)
- Assigned shipments in tenant schema:
  - **Hard POD** shipment (`pod_type=Hard`) for list/submit
  - **COD** shipment for payment collection
- Upload files under tenant-scoped paths (or disable strict storage checks in dev):

  `mobile_driver_uploads/{{tenant_schema}}/{{driver_id}}/{{shipment_id}}/…`

## Import

1. Postman → **Import**:
   - `Iroad_Mobile_Driver_Ops_Staging.postman_collection.json`
   - `Iroad_Mobile_Ops_Staging.postman_environment.json`
2. Select environment **Iroad Mobile — Ops Staging (Local)**.
3. Set required variables (below).

## Required variables

| Variable | Example | Notes |
|----------|---------|--------|
| `bearer_token` | `eyJ…` | Driver access JWT |
| `tenant_header` | `tenant_acme` | `X-Tenant-ID` — match JWT `tenant_schema` |
| `tenant_schema` | `tenant_acme` | Synced to `tenant_header` by collection |
| `driver_id` | UUID | From JWT — upload path prefix |
| `shipment_id` | UUID | Driver-owned Hard POD / COD shipment |

### Headers (every request)

```http
Authorization: Bearer {{bearer_token}}
X-Tenant-ID: {{tenant_header}}
Accept: application/json
Accept-Language: {{accept_language}}
X-Request-ID: {{request_id}}
```

Collection-level Bearer auth applies; individual requests also send `X-Tenant-ID`.

## Recommended run order

### Hard POD

| # | Request | Expected |
|---|---------|----------|
| 1 | **01 → 1. GET Pending list** | 200, `data.items[]` |
| 2 | **02 → 1. POST Submit custody** | 201, `custody_submission` |
| 3 | **02 → 2. POST Replay submit** | 200, `replayed: true` |
| 4 | **02 → 3. Wrong shipment** | 403/404 |
| 5 | **02 → 4. Wrong driver / not Hard POD** | 400/403 |

### Payment Collection

| # | Request | Expected |
|---|---------|----------|
| 1 | **03 → 1. Collect COD** | 201, `payment_bundle` |
| 2 | **03 → 2. Replay payment** | 200, `replayed: true` |
| 3 | **03 → 3. Duplicate payment** | 4xx `duplicate_payment` |
| 4 | **03 → 4. Variance** | 201, `variance_detected: true` (use fresh shipment) |
| 5 | **03 → 5. Wrong tenant** | 403 `tenant_mismatch` |

### Issues

| # | Request | Expected |
|---|---------|----------|
| 1 | **04 → 1. Delay report** | 201, `issue` + `escalation` |
| 2 | **04 → 2. Breakdown report** | 201, `blocking_recommended` may be true |
| 3 | **04 → 3. Escalation flow** | 201, `escalation_state: escalated` |
| 4 | **04 → 4. Issue replay** | 200, `replayed: true` |
| 5 | **04 → 5. Job Detail unresolved** | 200, `operational_issues`, `unresolved_issue_count` |

## Capabilities & prep-only model

These APIs **stage evidence** only. Workflow progression requires **Execute Action** (`mobile.driver.execute`).

| Staged artifact | Execute promotion |
|-----------------|-------------------|
| Hard POD custody | Hard POD action (e.g. A8) |
| Payment bundle | COD action (e.g. A9) via `client_payment_id` |
| Operational issue | Advisory on Job Detail / execute warnings |

## Troubleshooting

| Symptom | Check |
|---------|--------|
| 401 | Paste valid `bearer_token` |
| 403 `forbidden` | `shipment_id` not assigned to driver |
| 403 `tenant_mismatch` | Align `tenant_header` with JWT or omit header |
| 400 `tenant_required` | Set `tenant_header` / `tenant_schema` |
| `not_hard_pod_shipment` | Use Hard POD shipment for submit |
| `duplicate_payment` | Shipment already has staged/collected payment |
| `amount_ceiling_exceeded` | `payment_amount_full` > shipment COD amount |
| Empty Hard POD list | No Hard POD shipments assigned to driver |

## Regenerate collection

```bash
python mobile_api/postman/_generate_ops_staging_collection.py
```
