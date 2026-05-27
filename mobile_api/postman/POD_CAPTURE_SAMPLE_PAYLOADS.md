# POD Capture — Sample Payloads

Reference bodies for `Iroad_Mobile_Driver_POD_Capture` Postman collection.

Base URL: `{{base_url}}` = `http://127.0.0.1:8000/api/v1/mobile`

---

## Headers (all authenticated requests)

```http
Authorization: Bearer {{bearer_token}}
Content-Type: application/json
Accept: application/json
Accept-Language: en
X-Tenant-ID: {{tenant_header}}
X-Request-ID: postman-{{$guid}}
```

---

## 1. POD image capture (digital)

`POST /driver/jobs/shipments/{{shipment_id}}/pod/capture/`

```json
{
  "client_capture_id": "550e8400-e29b-41d4-a716-446655440001",
  "workflow_version": "2026-05-26T10:00:00+00:00",
  "content_hash": "shipment-version-token-from-job-detail",
  "pod_type": "digital",
  "notes": "Delivered to consignee — digital POD",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "media": [
    {
      "media_type": "photo",
      "file_ref": "mobile_driver_uploads/tenant_acme/drv-uuid/ship-uuid/pod_capture/digital-photo.jpg",
      "file_name": "digital-photo.jpg",
      "description": "Delivery proof photo"
    }
  ]
}
```

**201 response `data` (abbreviated):**

```json
{
  "capture_bundle": {
    "capture_bundle_id": "bundle-uuid",
    "client_capture_id": "550e8400-e29b-41d4-a716-446655440001",
    "status": "ready",
    "staged_media": [{ "media_type": "photo", "file_ref": "..." }],
    "execute_ready": true,
    "replayed": false
  },
  "compliance": {
    "validated": true,
    "pod_type": "digital",
    "requirements": { "gps": true, "photo": true, "photo_min_count": 1 },
    "summary": { "gps_satisfied": true, "photo_count": 1, "media_count": 1 }
  },
  "sync_metadata": {
    "content_hash": "...",
    "workflow_version": "..."
  },
  "next_step": {
    "requires_execute_action": true,
    "bundle_id": "bundle-uuid",
    "capture_bundle_id": "bundle-uuid",
    "target_action_code": "POD_CAP"
  }
}
```

---

## 2. POD video capture

```json
{
  "client_capture_id": "{{$guid}}",
  "workflow_version": "{{pod_workflow_version}}",
  "content_hash": "{{pod_content_hash}}",
  "pod_type": "video",
  "notes": "Video POD evidence",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "media": [
    {
      "media_type": "video",
      "file_ref": "mobile_driver_uploads/{{tenant_schema}}/{{driver_id}}/{{shipment_id}}/pod_capture/delivery-video.mp4",
      "file_name": "delivery-video.mp4"
    }
  ]
}
```

---

## 3. Signature POD capture

```json
{
  "client_capture_id": "{{$guid}}",
  "workflow_version": "{{pod_workflow_version}}",
  "content_hash": "{{pod_content_hash}}",
  "pod_type": "signature",
  "notes": "Signed by recipient",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "media": [
    {
      "media_type": "signature",
      "file_ref": "mobile_driver_uploads/{{tenant_schema}}/{{driver_id}}/{{shipment_id}}/pod_capture/signature.png",
      "file_name": "signature.png"
    }
  ]
}
```

---

## 4. Hard POD capture

```json
{
  "client_capture_id": "{{$guid}}",
  "workflow_version": "{{pod_workflow_version}}",
  "content_hash": "{{pod_content_hash}}",
  "pod_type": "hard",
  "notes": "Physical delivery note collected",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "media": [
    {
      "media_type": "photo",
      "file_ref": "mobile_driver_uploads/{{tenant_schema}}/{{driver_id}}/{{shipment_id}}/pod_capture/hard-copy-scan.jpg",
      "file_name": "hard-copy-scan.jpg",
      "description": "Scanned delivery note"
    }
  ]
}
```

---

## 5. Multi-page POD capture

```json
{
  "client_capture_id": "{{$guid}}",
  "workflow_version": "{{pod_workflow_version}}",
  "content_hash": "{{pod_content_hash}}",
  "pod_type": "multi_page",
  "notes": "Multi-page POD document",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "media": [
    {
      "media_type": "photo",
      "file_ref": ".../pod_capture/page-1.jpg",
      "file_name": "page-1.jpg"
    },
    {
      "media_type": "document",
      "file_ref": ".../pod_capture/page-2.jpg",
      "file_name": "page-2.jpg"
    }
  ]
}
```

---

## 6. Replay-safe capture

Repeat request **1** with the **same** `client_capture_id`:

- First call: **201**, `replayed: false`
- Second call: **200**, `replayed: true`, same `capture_bundle_id`

---

## 7. Wrong shipment

`POST .../shipments/{{foreign_shipment_id}}/pod/capture/`

Same body as digital capture → expect **403/404**.

---

## 8. Wrong driver (orphan upload)

```json
{
  "media": [
    {
      "media_type": "photo",
      "file_ref": "mobile_driver_uploads/{{tenant_schema}}/{{wrong_driver_id}}/{{shipment_id}}/pod_capture/orphan.jpg"
    }
  ]
}
```

→ expect **403** `orphan_upload`.

---

## 9. Wrong tenant

Same capture URL with header:

```http
X-Tenant-ID: wrong-tenant-schema
```

→ expect **403** `tenant_mismatch` or auth error.

---

## 10. Expired bundle (execute)

Use execute body with `capture_bundle_id` = expired bundle UUID → **410** `bundle_expired`.

---

## 11. Invalid MIME

```json
{
  "media": [
    {
      "media_type": "photo",
      "file_ref": ".../pod_capture/malware.exe",
      "file_name": "malware.exe"
    }
  ]
}
```

→ expect **400** `media_extension_not_allowed` / `media_mime_not_allowed`.

---

## 12. Missing GPS

Omit `latitude` and `longitude` when Action Master requires GPS:

```json
{
  "client_capture_id": "{{$guid}}",
  "workflow_version": "{{pod_workflow_version}}",
  "content_hash": "{{pod_content_hash}}",
  "pod_type": "digital",
  "notes": "No GPS",
  "media": [{ "media_type": "photo", "file_ref": ".../digital-photo.jpg" }]
}
```

→ expect **400** `gps_required`.

---

## 13. Invalid POD type

```json
{
  "pod_type": "not_a_valid_type",
  "media": [{ "media_type": "photo", "file_ref": ".../photo.jpg" }]
}
```

→ expect **400** `invalid_pod_capture_type`.

---

## 14. Execute promotion flow

`POST /driver/jobs/shipment/{{shipment_id}}/actions/{{execute_pod_action_code}}/execute/`

After successful capture (**request 1**):

```json
{
  "client_action_id": "{{$guid}}",
  "workflow_version": "{{pod_workflow_version}}",
  "content_hash": "{{pod_content_hash}}",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "notes": "Execute POD with staged bundle",
  "capture_bundle_id": "{{capture_bundle_id}}",
  "media": []
}
```

**201 response excerpt:**

```json
{
  "execution": {
    "action_log_id": "...",
    "reused_existing": false
  },
  "pod_capture": {
    "promoted_bundle_id": "{{capture_bundle_id}}",
    "promoted_media": [
      {
        "media_type": "photo",
        "file_ref": ".../digital-photo.jpg",
        "action_log_media_id": "..."
      }
    ],
    "compliance": {
      "validated": true,
      "requirements": { "gps": true, "photo": true }
    },
    "replayed": false
  }
}
```

### 14b — Execute idempotent replay

Repeat **14** with the same `client_action_id` → **200**, `execution.reused_existing: true`.

### 14c — Duplicate promotion

New `client_action_id`, same `capture_bundle_id` after bundle already promoted → **409** `bundle_already_promoted`.

---

## Optional fields

| Field | Purpose |
|-------|---------|
| `target_action_code` | Explicit Action Master row (else default POD action resolved) |
| `pod_capture_type` | Alias for `pod_type` |
| `entity_versions` | Optional version map for future stale guards |

## Execute bundle id aliases

Any of these promote the staged bundle:

- `capture_bundle_id` (preferred)
- `pod_capture_bundle_id`
- `bundle_id`
