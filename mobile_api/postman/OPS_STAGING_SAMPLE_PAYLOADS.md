# Ops Staging — Sample Payloads

Reference bodies for Hard POD, Payment Collection, and Issue Reporting.

Base URL: `{{base_url}}` = `http://127.0.0.1:8000/api/v1/mobile`

---

## Hard POD List

**`GET /driver/hard-pod/pending/?limit=50`**

No body.

### Success `data`

```json
{
  "items": [
    {
      "shipment_id": "uuid",
      "shipment_no": "SH-001",
      "pod_type": "Hard",
      "shipment_status": "Loaded",
      "custody_status": "pending",
      "hard_pod_pending": true
    }
  ],
  "count": 1
}
```

---

## Hard POD Submit

**`POST /driver/hard-pod/submit/`**

### Request

```json
{
  "client_submission_id": "hard-pod-550e8400-e29b-41d4-a716-446655440000",
  "shipment_id": "{{shipment_id}}",
  "receiver_name": "Jane Receiver",
  "receiver_contact": "+966500000000",
  "handoff_notes": "Left with security desk",
  "latitude": 24.7136,
  "longitude": 46.6753,
  "media": [
    {
      "media_type": "photo",
      "file_ref": "mobile_driver_uploads/{{tenant_schema}}/{{driver_id}}/{{shipment_id}}/hard_pod/scan-001.jpg",
      "file_name": "scan-001.jpg",
      "mime_type": "image/jpeg",
      "sort_order": 1
    }
  ]
}
```

### Success `data` (201)

```json
{
  "custody_submission": {
    "submission_id": "uuid",
    "client_submission_id": "hard-pod-550e8400-…",
    "shipment_id": "uuid",
    "receiver_name": "Jane Receiver",
    "replayed": false
  },
  "timeline_preview": [],
  "next_step": {
    "requires_execute_action": true
  }
}
```

### Replay (200)

Same body + same `client_submission_id` → `custody_submission.replayed: true`.

### Errors

| Code | HTTP | When |
|------|------|------|
| `forbidden` | 403 | Wrong driver / shipment |
| `job_not_found` | 404 | Unknown shipment |
| `not_hard_pod_shipment` | 400 | Digital POD shipment |
| `submission_shipment_mismatch` | 409 | Replay with different `shipment_id` |
| `orphan_upload` | 400 | `file_ref` outside driver prefix |

---

## Payment Collection

**`POST /driver/payments/collect/`**

### Request — full COD

```json
{
  "client_payment_id": "pay-550e8400-e29b-41d4-a716-446655440000",
  "shipment_id": "{{shipment_id}}",
  "amount": "100.00",
  "notes": "COD collected via Postman",
  "payment_mode": "COD",
  "proof_media": [
    {
      "media_type": "photo",
      "file_ref": "mobile_driver_uploads/{{tenant_schema}}/{{driver_id}}/{{shipment_id}}/payment_collection/proof.jpg",
      "file_name": "proof.jpg",
      "mime_type": "image/jpeg",
      "sort_order": 1
    }
  ]
}
```

### Success `data` (201)

```json
{
  "payment_bundle": {
    "bundle_id": "uuid",
    "client_payment_id": "pay-550e8400-…",
    "shipment_id": "uuid",
    "amount": "100.00",
    "expected_amount": "100.00",
    "variance_detected": false,
    "payment_mode": "COD",
    "replayed": false
  },
  "reconciliation": {
    "variance_detected": false,
    "expected_amount": "100.00",
    "collected_amount": "100.00"
  },
  "next_step": {
    "requires_execute_action": true
  }
}
```

### Variance example

```json
{
  "amount": "90.00"
}
```

→ `reconciliation.variance_detected: true` (partial collect).

### Errors

| Code | HTTP | When |
|------|------|------|
| `duplicate_payment` | 409 | Shipment already has payment staged |
| `not_cod_shipment` | 400 | Non-COD order type |
| `amount_ceiling_exceeded` | 400 | Amount > expected COD |
| `invalid_amount` | 400 | Amount ≤ 0 |
| `tenant_mismatch` | 403 | Wrong `X-Tenant-ID` |

---

## Issue Reporting

**`POST /driver/issues/report/`**

### Delay report

```json
{
  "client_issue_id": "issue-550e8400-e29b-41d4-a716-446655440000",
  "shipment_id": "{{shipment_id}}",
  "issue_type": "delay",
  "severity": "medium",
  "notes": "Heavy traffic on highway — ETA delayed 45 minutes",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "media": [
    {
      "media_type": "photo",
      "file_ref": "mobile_driver_uploads/{{tenant_schema}}/{{driver_id}}/{{shipment_id}}/issues/delay-traffic.jpg",
      "file_name": "delay-traffic.jpg"
    }
  ]
}
```

### Vehicle breakdown

```json
{
  "client_issue_id": "issue-bd-…",
  "shipment_id": "{{shipment_id}}",
  "issue_type": "vehicle_breakdown",
  "severity": "high",
  "notes": "Engine failure — awaiting roadside assistance",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "media": []
}
```

### Escalation flow (auto-escalate)

```json
{
  "client_issue_id": "issue-esc-…",
  "shipment_id": "{{shipment_id}}",
  "issue_type": "route_blocked",
  "severity": "critical",
  "notes": "Highway closed — police diversion",
  "latitude": 25.2048,
  "longitude": 55.2708,
  "media": []
}
```

`issue_type` values: `delay`, `vehicle_breakdown`, `customer_unavailable`, `payment_dispute`, `pod_issue`, `accident`, `route_blocked`, `other`.

`severity` values: `low`, `medium`, `high`, `critical`.

### Success `data` (201)

```json
{
  "issue": {
    "issue_id": "uuid",
    "client_issue_id": "issue-550e8400-…",
    "issue_type": "delay",
    "severity": "medium",
    "escalation_state": "open",
    "blocking_recommended": false,
    "replayed": false
  },
  "escalation": {
    "escalation_state": "escalated",
    "auto_escalated": true
  },
  "timeline_preview": {},
  "workflow_impact": {
    "blocking_recommended": true,
    "unresolved_issue_count": 1,
    "has_unresolved_issues": true,
    "workflow_mutation_performed": false,
    "execute_action_required_for_progression": false
  },
  "next_step": {
    "requires_execute_action": false
  }
}
```

Critical + high-impact types may set `escalation_state` to `escalated` immediately.

---

## Job Detail — unresolved issues

**`GET /driver/jobs/shipment/{{shipment_id}}/`**

Top-level fields (after operational issues integration):

```json
{
  "operational_issues": [
    {
      "issue_id": "uuid",
      "issue_type": "delay",
      "severity": "medium",
      "escalation_state": "open",
      "blocking_recommended": false,
      "unresolved": true
    }
  ],
  "unresolved_issue_count": 1,
  "blocking_recommendation": false,
  "timeline": {
    "timeline_preview": [
      {
        "event_type": "issue",
        "issue_timeline_kind": "issue_opened",
        "action_label": "Delay opened",
        "authority": "operational_issue"
      }
    ],
    "includes_operational_issues": true
  },
  "alerts": {
    "has_operational_issues": true,
    "escalation_alerts": []
  }
}
```

Timeline kinds: `issue_opened`, `issue_escalated`, `issue_resolved`, `issue_rejected`.

---

## Standard envelope

```json
{
  "status": "success",
  "message": "…",
  "message_key": "mobile.success.…",
  "data": { },
  "meta": { "request_id": "…" }
}
```

Error:

```json
{
  "status": "error",
  "error": {
    "code": "forbidden",
    "message": "…",
    "message_key": "mobile.…"
  }
}
```
