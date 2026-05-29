# Driver History API

Read-only completed-job audit trail per IRoute §14.7.1.

**Base:** `/api/v1/mobile/`  
**Capability:** `mobile.driver.history`  
**Auth:** `Authorization: Bearer <access_token>`

## List + filter preview

`GET /driver/history/`

| Query | Description |
|-------|-------------|
| `shipment_no` | Filter by shipment number (partial match) or UUID |
| `date` | Job date — `YYYY-MM-DD` or `DD-MM-YYYY` |
| `count_only` | `true` — filter modal preview (`results_found` only) |

Returns the **full filtered list** in one response (no cursor pagination; capped at `MOBILE_HISTORY_LIST_MAX_RESULTS`, default 200).

**Success `data`:**

```json
{
  "items": [
    {
      "shipment_id": "uuid",
      "shipment_no": "SH-2026-1001",
      "booking_no": "BK-000010",
      "status": "Completed",
      "final_state": "Closed",
      "route": {
        "type": "Round",
        "origin_city": "Jeddah",
        "destination_city": "Riyadh",
        "route_display": "Jeddah → Riyadh"
      },
      "payment_method": "COD",
      "transaction_type": "COD",
      "client_name": "Al Marai Company",
      "job_date": "2026-02-10",
      "shipment_date": "2026-02-10",
      "actions_fired_count": 8,
      "read_only": true
    }
  ],
  "count": 1,
  "results_found": 1
}
```

## History detail

`GET /driver/history/<shipment_id>/`

`shipment_id` = UUID or `shipment_no`.

**Success `data`:**

```json
{
  "summary": {
    "booking_no": "BK-000010",
    "shipment_no": "SH-2026-1001",
    "status": "Completed",
    "route_type": "Round",
    "order_type": "Credit",
    "payment_method": "Credit",
    "transaction_type": "Credit",
    "origin": { "city": "Jeddah", "address": "Warehouse 4, ..." },
    "destination": { "city": "Riyadh", "address": "Al Marai Main Depot, ..." },
    "client_name": "Al Marai Company",
    "job_date": "2026-02-10",
    "read_only": true
  },
  "workflow_status": [
    {
      "step_key": "pickup",
      "label": "Pickup",
      "completed": true,
      "location": "...",
      "display_timestamp": "11 Feb 2026 | 09:00 AM",
      "media": []
    }
  ],
  "timeline": {
    "scope": "shipment",
    "events": [],
    "append_only": true,
    "authority": "action_log"
  },
  "actions_fired_count": 8,
  "history_projection_version": "1"
}
```

## Rules

- Only **Closed** or **Cancelled** shipments appear in History.
- Active / in-flight jobs stay on Dashboard and Job Detail.
- Detail is **read-only** — no workflow mutations.
- Timeline is derived from **Action Log** (append-only, P1).

## Errors

| Code | HTTP | When |
|------|------|------|
| `invalid_date` | 400 | Bad `date` query |
| `history_not_available` | 400 | Shipment not terminal |
| `forbidden` | 403 | Wrong driver |
| `job_not_found` | 404 | Unknown shipment |
