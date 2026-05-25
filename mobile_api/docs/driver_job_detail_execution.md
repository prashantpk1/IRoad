# Job Detail — execute action APIs

Mobile drivers execute workflow actions through the same transactional pipeline as the portal Action Log, without duplicating `get_allowed_actions()` policy.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/mobile/driver/jobs/shipments/{shipment_id}/actions/execute/` | Execute action on shipment job |
| `POST` | `/api/v1/mobile/driver/jobs/movements/{movement_id}/actions/execute/` | Execute action on movement job |

**Auth:** mobile JWT + `mobile.driver.jobs.execute` capability (`HasDriverJobsExecuteAccess`).

See `mobile_api/docs/driver_job_execution_security.md` for the full security pipeline.

**Content types:** `application/json` or `multipart/form-data` (media uploads).

## Request body

| Field | Required | Notes |
|-------|----------|-------|
| `action_id` | yes | UUID of `TenantOperationAction` |
| `idempotency_key` | recommended | Dedupes retries (128 chars) |
| `source_ref` | optional | Secondary dedupe with `source_channel=mobile_driver` |
| `notes` | per action | Validated when Action Master requires note |
| `latitude`, `longitude`, `map_link` | per action | GPS validation from metadata projection |
| `log_date` | optional | Defaults to now (tenant TZ) |
| `cod_amount` | A9 / collect payment | Decimal; falls back to shipment `cod_amount` |
| `media` | per action | JSON array of `{media_type, description, captured_at}` |
| `media_file` | per action | Multipart file(s); indexed with `media_type[]` etc. |

## Execution pipeline (single transaction)

```
DriverJobExecuteService
  → validate_mobile_execution_payload()     # GPS / media / note / COD
  → ActionExecutionService.execute_driver_action()
       → validate_driver_action_execution()  # wraps validate_operation_action_allowed()
       → idempotency / recent-duplicate guard
       → append-only TenantOperationActionLog.save()
       → apply_execution_side_effects()      # POD/COD/movement/shipment impacts
       → sync_shipment_status_from_action_log() (when shipment linked)
  → save_action_log_media_from_mobile_request()  # skipped if reused_existing
  → refresh shipment/movement from DB
  → workflow snapshot (allowed_actions + execution_state + latest_action)
```

**Do not** bypass `validate_operation_action_allowed()` or hardcode status progression.

## Response (`200`)

```json
{
  "success": true,
  "data": {
    "execution": {
      "log_id": "uuid",
      "log_no": "OAL-000123",
      "log_date": "2026-05-21T10:00:00+00:00",
      "action_code": "A5",
      "action_label": "Depart In Transit",
      "reused_existing": false,
      "source_channel": "mobile_driver",
      "media_saved_count": 1
    },
    "workflow": {
      "allowed_actions": { "...": "same shape as GET .../actions/" },
      "execution_state": { "shipment_status", "derived_status", "operational_stage", "in_sync" },
      "latest_action": { "...": "JobLatestActionSummary" },
      "shipment_status": "In Transit",
      "movement_status": null,
      "operational_stage": "In Transit"
    }
  },
  "meta": {
    "reused_existing": false,
    "log_no": "OAL-000123",
    "workflow_source": "operation_execution.get_allowed_actions"
  }
}
```

## Error codes

| HTTP | `code` | When |
|------|--------|------|
| 400 | `execution_validation_failed` | Missing GPS/photo/note/COD |
| 400 | `invalid_action` | Unknown `action_id` |
| 403 | `action_not_allowed` | Policy engine rejected action |
| 404 | `job_not_found` | Shipment/movement not driver-scoped |

## Idempotency

1. **`idempotency_key`** — global lookup on `TenantOperationActionLog.idempotency_key`; returns existing log with `reused_existing: true` (no new side effects, no duplicate media).
2. **`source_ref` + `source_channel=mobile_driver`** — same behavior when key absent.
3. **Recent duplicate guard** — when neither key nor ref provided, `find_recent_duplicate()` may return a recent matching log.

## Shipment execution sub-stages

When a job is **shipment-linked** (Created/Loaded), pickup (A2) and loading (A3) run on the
shipment action log — not blocked. Booking-only Action Log UI still requires no active shipment.

| Sub-stage | Meaning |
|-----------|---------|
| `pickup` | A2 not yet logged on shipment |
| `loading` | A2 done, A3 pending |
| `pre_transit` | A2+A3 done, status still Created/Loaded |
| `in_transit` … | Maps from `shipment_status` forward |

Policy: `iroad_tenants/operation_runtime/shipment_execution_stage.py` + `operation_execution._action_is_allowed`.

## Movement execution sub-stages (empty / movement-only)

When **no shipment** is on the action context, policy uses the movement engine:

| Sub-stage | Meaning |
|-----------|---------|
| `created` | `Scheduled`, start not logged |
| `started` | Start logged / `In Progress` |
| `in_transit` | In-transit milestone logged |
| `arrived` | Arrival milestone logged |
| `completed` / `cancelled` | Terminal column status |

Forward graph: `movement_state_machine.py` + log sequencing in `movement_action_validator.py`.

Packages: `movement_execution_engine.py`, `movement_stage_derivation.py`, `movement_action_validator.py`.

## Architecture map

| Layer | Module |
|-------|--------|
| Views | `mobile_api/views/driver_job_execute.py` |
| Orchestration | `mobile_api/services/driver_job_execute_service.py` |
| Validation | `mobile_api/helpers/action_execution_validation.py` |
| Media | `mobile_api/helpers/action_log_media.py` |
| Serializers | `mobile_api/serializers/driver_job_execute.py` |
| Policy + log + effects | `iroad_tenants/services/action_execution_service.py` |
| Allowed actions refresh | `OperationExecutionService.get_allowed_driver_actions()` |

## Related read APIs

- `GET .../shipments/{id}/` — job detail snapshot
- `GET .../shipments/{id}/actions/` — allowed actions (membership from engine only)
