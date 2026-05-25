# Driver Job Detail APIs

Lightweight execution snapshots for shipment and movement screens. No portal serializers, no full timelines.

## Endpoints

| Method | Path | Capability |
|--------|------|------------|
| `GET` | `/api/v1/mobile/driver/jobs/shipments/{shipment_id}/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/movements/{movement_id}/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/shipments/{shipment_id}/actions/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/movements/{movement_id}/actions/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/shipments/{shipment_id}/timeline/` | `mobile.driver.jobs` |
| `GET` | `/api/v1/mobile/driver/jobs/movements/{movement_id}/timeline/` | `mobile.driver.jobs` |
| `POST` | `/api/v1/mobile/driver/jobs/shipments/{shipment_id}/actions/execute/` | `mobile.driver.jobs.execute` |
| `POST` | `/api/v1/mobile/driver/jobs/shipments/{shipment_id}/upload-pod/` | `mobile.driver.jobs.execute` |
| `POST` | `/api/v1/mobile/driver/jobs/shipments/{shipment_id}/collect-cod/` | `mobile.driver.jobs.execute` |

**Auth:** `Authorization: Bearer <access_token>` (tenant from JWT `tenant_schema`).

See `mobile_api/docs/driver_job_pod_cod.md` for POD/COD compliance flow and
`mobile_api/docs/driver_job_execution_security.md` for execution RBAC and guards.

## Timeline API (full history)

Cursor-paginated execution feed (no offset). Bounded page size; capped media previews per log.

| Param | Default | Max | Description |
|-------|---------|-----|-------------|
| `page_size` | 20 | 50 | Rows per page |
| `cursor` | — | — | Opaque token from `pagination.next_cursor` |

Each `items[]` row includes: `action_name`, `execution_time`, `driver_name`, `gps`, `notes`, `media_previews` (max 3/log), `status_impacts`, `events` (POD/COD/reversal flags).

Detail snapshot `timeline_preview` remains a small preview (≤15 rows); use **timeline** endpoints for scrollable history.

## Query params (detail)

| Param | Default | Description |
|-------|---------|-------------|
| `include_timeline` | `1` | Set `0` to skip timeline preview |
| `include_actions` | `1` | Set `0` to skip Action Engine allowed-actions call |

## Allowed actions API

**Authoritative membership:** `iroad_tenants.operation_execution.get_allowed_actions()` only.

**Not used for which buttons appear:** `next_action_hint`, shipment-status heuristics, or static mobile lists.

Each action in `data.allowed_actions.actions[]` includes:

| Field | Source |
|-------|--------|
| `action_id`, `action_code` | Action Master row |
| `action_name`, `execution_label` | Localized labels |
| `requires_gps`, `requires_photo`, `requires_video`, `requires_note` | Metadata projection from Action Master + IRoute evidence rules |
| `action_category` | `action_scope` / `sequence_category` |
| `execution_order` | `sequence_number` |
| `current_stage` | Reporting only (shipment/movement status) |
| `execution_requirements` | Structured capture flags |

`meta.workflow_source` is always `operation_execution.get_allowed_actions`.

## Response `data.snapshot` fields

| Block | Description |
|-------|-------------|
| `job_summary` | Flat job header (id, no, status, route, links) |
| `execution_stage` | Current UX stage label |
| `current_workflow_state` | Status + derived state + indicator flags |
| `shipment` / `movement` | Entity blocks |
| `route` / `route_summary` | Route labels |
| `truck` / `truck_summary` | Truck snapshot |
| `driver_context` | Authenticated driver |
| `pod` / `cod` | Execution gates |
| `latest_action` | Latest action log summary |
| `timeline_preview` | Max 15 rows (configurable) |
| `allowed_actions_summary` | Action Engine output |
| `operational_indicators` | `needs_pod`, `needs_cod`, `is_active`, etc. |

## Query budget (typical, all flags on)

| Step | Queries |
|------|---------|
| Shipment row + addresses + truck | 1 |
| Active movement | 0–1 |
| Latest action | 1 |
| Allowed actions (engine) | 1 (+ action master scan) |
| Timeline preview | 1 |

Use `include_timeline=0` / `include_actions=0` on poll-heavy refreshes.

## Errors

| Code | HTTP | Meaning |
|------|------|---------|
| `job_not_found` | 404 | ID invalid or not in driver scope |
| `invalid_shipment_id` / `invalid_movement_id` | 400 | Malformed UUID |
| `job_detail_payload_too_large` | 413 | Strict payload cap exceeded |

## Modules

- `mobile_api/services/driver_job_detail_service.py` — orchestration
- `mobile_api/services/job_detail_snapshot_service.py` — tenant reads
- `mobile_api/helpers/job_detail_projections.py` — flat DTO
- `iroad_tenants.services.OperationExecutionService` — allowed actions
