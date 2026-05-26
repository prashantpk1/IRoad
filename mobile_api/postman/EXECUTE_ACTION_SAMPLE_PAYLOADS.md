# Execute Action API — Sample Request Payloads

Base URL (environment): `{{base_url}}` → default `http://127.0.0.1:8000/api/v1/mobile`

Endpoint pattern:

```
POST {{base_url}}/driver/jobs/<job_type>/<job_id>/actions/<action_code>/execute/
```

Headers (all live requests):

| Header | Value |
|--------|--------|
| `Authorization` | `Bearer {{bearer_token}}` |
| `Content-Type` | `application/json` |
| `Accept` | `application/json` |
| `X-Tenant-ID` | `{{tenant_schema}}` (omit only for bearer-only tests) |
| `X-Request-ID` | `postman-{{$guid}}` |

---

## 1. Shipment execute (happy path)

**URL:** `.../jobs/shipment/{{shipment_id}}/actions/{{execute_action_code}}/execute/`

```json
{
  "client_action_id": "550e8400-e29b-41d4-a716-446655440001",
  "workflow_version": "wf-abc123",
  "content_hash": "a1b2c3d4e5f6...64chars-from-job-detail-sync_metadata",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "notes": "Arrived at pickup — Postman",
  "media": []
}
```

**Expected:** `201` + `data.execution.reused_existing: false`

---

## 2. Empty move execute

**URL:** `.../jobs/movement/{{movement_id}}/actions/{{execute_action_code}}/execute/`

```json
{
  "client_action_id": "550e8400-e29b-41d4-a716-446655440002",
  "workflow_version": "wf-empty-01",
  "content_hash": "hash-from-empty-move-job-detail",
  "latitude": 25.10,
  "longitude": 55.20,
  "notes": "Empty move leg started",
  "media": []
}
```

**Expected:** `201`; `data.pod_cod` is `{}`

---

## 3. POD execute

Set `execute_pod_action_code` from Job Detail `workflow.allowed_actions` where POD is pending (`pod_cod.pod_pending: true`). Often a delivery/POD capture action configured in Action Master.

**URL:** `.../jobs/shipment/{{shipment_id}}/actions/{{execute_pod_action_code}}/execute/`

```json
{
  "client_action_id": "550e8400-e29b-41d4-a716-446655440003",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "notes": "POD captured",
  "media": [
    {
      "media_type": "photo",
      "file_ref": "tenant-uploads/pod/photo-001.jpg",
      "file_name": "pod-front.jpg",
      "description": "Delivery proof"
    },
    {
      "media_type": "signature",
      "file_ref": "tenant-uploads/pod/signature-001.png",
      "file_name": "receiver-sign.png"
    }
  ]
}
```

**Expected:** `201` when action allows; may trigger POD side effects in kernel.

---

## 4. COD execute

Set `execute_cod_action_code` when `pod_cod.cod_pending: true`.

```json
{
  "client_action_id": "550e8400-e29b-41d4-a716-446655440004",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "notes": "COD collected",
  "mobile_cod_amount": "150.00",
  "media": []
}
```

**Expected:** `201` when COD action is in `allowed_actions`.

---

## 5. Hard POD execute

Set `execute_hard_pod_action_code` when `pod_cod.hard_pod_pending: true`.

```json
{
  "client_action_id": "550e8400-e29b-41d4-a716-446655440005",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "notes": "Hard POD compliance",
  "media": [
    {
      "media_type": "photo",
      "file_ref": "tenant-uploads/hard-pod/scan-001.jpg",
      "file_name": "hard-pod.jpg"
    }
  ]
}
```

---

## 6. Idempotent replay (retry)

Send **the same** body as a successful execute (same `client_action_id`, same job, same `action_code`).

```json
{
  "client_action_id": "550e8400-e29b-41d4-a716-446655440001",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "notes": "Arrived at pickup — Postman",
  "media": []
}
```

**Expected:** `200` + `data.execution.reused_existing: true` + `idempotent_replay: true`

---

## 7. Stale workflow rejection

Use hashes **not** matching current Job Detail `sync_metadata`.

```json
{
  "client_action_id": "550e8400-e29b-41d4-a716-446655440099",
  "workflow_version": "stale-workflow-version-intentionally-wrong",
  "content_hash": "stale-content-hash-intentionally-wrong",
  "latitude": 25.0,
  "longitude": 55.0,
  "notes": "",
  "media": []
}
```

**Expected:** `409` + `data.error_code`: `stale_content_hash` or `stale_workflow_version` + `refresh_required: true`

---

## 8. Wrong tenant

Same body as happy path; set header `X-Tenant-ID: {{wrong_tenant_id}}` (must not match JWT `tenant_schema`).

**Expected:** `403` + `tenant_mismatch` (authentication layer) or `400` `tenant_required` if schema cannot be resolved.

---

## 9. Wrong driver (foreign job)

**URL:** `.../jobs/shipment/{{foreign_shipment_id}}/actions/{{execute_action_code}}/execute/`

```json
{
  "client_action_id": "550e8400-e29b-41d4-a716-446655440098",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": 25.0,
  "longitude": 55.0,
  "notes": "",
  "media": []
}
```

**Expected:** `403` + `forbidden` / `job_not_found` (ownership guard)

---

## 10. Missing idempotency key

Omit `client_action_id` or send empty string:

```json
{
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": 25.0,
  "longitude": 55.0,
  "notes": "",
  "media": []
}
```

**Expected:** `400` validation_failed — field `client_action_id` required / `idempotency_key_required`

---

## 11. Invalid action

**URL:** `.../actions/{{invalid_action_code}}/execute/` (default `ZZZ_NOT_ALLOWED`)

```json
{
  "client_action_id": "550e8400-e29b-41d4-a716-446655440097",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "latitude": 25.0,
  "longitude": 55.0,
  "notes": "",
  "media": []
}
```

**Expected:** `400` + `action_not_allowed` or `action_not_found`

---

## 12. Evidence validation failure

Target an action whose Action Master requires GPS and/or photo, but send incomplete evidence:

```json
{
  "client_action_id": "550e8400-e29b-41d4-a716-446655440096",
  "workflow_version": "{{execute_workflow_version}}",
  "content_hash": "{{execute_content_hash}}",
  "notes": "",
  "media": []
}
```

(Omit `latitude` / `longitude` when GPS required, or `media: []` when photo/signature required.)

**Expected:** `400` + one of: `gps_required`, `photo_required`, `signature_required`, `notes_required`, `media_file_required`

---

## Success response `data` contract

```json
{
  "execution": {
    "job_type": "shipment",
    "job_id": "...",
    "action_code": "A2",
    "reused_existing": false,
    "idempotent_replay": false,
    "action_log_id": "...",
    "log_no": "OAL-...",
    "log_date": "2026-05-26T12:00:00+00:00",
    "idempotency_key": "550e8400-..."
  },
  "workflow": {
    "current_stage": "...",
    "next_action": {},
    "primary_action": {},
    "allowed_actions": []
  },
  "pod_cod": {},
  "timeline_preview": {
    "scope": "shipment",
    "timeline_preview": [],
    "timeline_cursor": "",
    "has_more": false
  },
  "sync_metadata": {
    "content_hash": "...",
    "workflow_version": "...",
    "entity_versions": {}
  },
  "alerts": {}
}
```
