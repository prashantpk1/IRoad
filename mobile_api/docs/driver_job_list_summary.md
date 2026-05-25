# Driver job list — summary API

`GET /api/v1/mobile/driver/jobs/summary/`

Capability: `mobile.driver.jobs` · Permission: `HasDriverJobsAccess`

## Purpose

Lightweight operational badge counts for the My Jobs landing screen. **Independent** from the home dashboard `data.counters` payload (no `completed_today`, `pending_actions`, etc.).

## Query budget

| Round-trip | Query |
|------------|--------|
| 1 | Shipment conditional `Count` (5 filters) |
| 2 | Movement conditional `Count` (3 filters) |

Driver scope: `driver_shipment_counter_scope_q` / `driver_movement_scope_q` (same as list feeds).

## Response

```json
{
  "status": 1,
  "message": "Job summary loaded successfully.",
  "message_key": "mobile.jobs.summary_success",
  "data": {
    "counters": {
      "active_shipments": 12,
      "completed_shipments": 45,
      "cancelled_shipments": 2,
      "active_movements": 5,
      "completed_movements": 30,
      "cancelled_movements": 1,
      "pod_pending": 3,
      "cod_pending": 2
    },
    "entity_types": ["shipment", "movement"]
  }
}
```

## Counter semantics

| Field | List route alignment |
|-------|----------------------|
| `active_shipments` | `/jobs/shipments/active/` |
| `completed_shipments` | `/jobs/shipments/completed/` |
| `cancelled_shipments` | `/jobs/shipments/cancelled/` |
| `pod_pending` | `/jobs/shipments/pod-pending/` |
| `cod_pending` | `/jobs/shipments/cod-pending/` |
| `active_movements` | `/jobs/movements/active/` |
| `completed_movements` | `/jobs/movements/completed/` |
| `cancelled_movements` | `/jobs/movements/cancelled/` |

POD/COD counts are **active in-flight** shipments only (reuses `shipment_pod_pending_filter_q` / `shipment_cod_pending_filter_q` from dashboard aggregations).

## Modules

| Module | Role |
|--------|------|
| `helpers/job_list_aggregations.py` | Tab-aligned `Q` filters |
| `services/driver_job_list_counters.py` | `build_job_list_counters()` |
| `services/driver_job_list_service.py` | `build_job_summary()` + tenant `schema_context` |
| `serializers/driver_job_list.py` | `JobSummarySerializer` |

## vs dashboard

| | Job summary | Dashboard counters |
|--|-------------|-------------------|
| Service | `build_job_list_counters` | `build_dashboard_counters` |
| Completed tabs | `completed_shipments` / `completed_movements` | `completed_today` / `completed_this_week` |
| POD field | `pod_pending` | `pending_pod` |
| Extra fields | — | `pending_actions` |
