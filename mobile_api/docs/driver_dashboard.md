# Driver Home Dashboard (mobile API)

## Endpoints

| Method | Path | Capability | Notes |
|--------|------|------------|--------|
| `GET` | `/api/v1/mobile/driver/dashboard/` | `mobile.driver.dashboard` | Full dashboard (`variant=full`, recent activity limit 10) |
| `GET` | `/api/v1/mobile/driver/dashboard/recent-activity/` | `mobile.driver.dashboard` | Merged feed only; optional `?limit=5` (max 10) |
| `GET` | `/api/v1/mobile/driver/dashboard/summary/` | `mobile.driver.dashboard` | Summary poll (`variant=summary`, recent activity limit 5) |
| `GET` | `/api/v1/mobile/driver/dashboard/notifications-summary/` | `mobile.driver.dashboard` | Notification summary only; optional `?variant=summary` |

**Auth:** `Authorization: Bearer <access_token>`. Tenant from JWT `tenant_schema`. Capability: `mobile.driver.dashboard` (driver principal only). See [driver_dashboard_security.md](./driver_dashboard_security.md).

## Response contract (`data`)

| Field | Description |
|-------|-------------|
| `variant` | `full` or `summary` |
| `welcome` | Landing header — nested `driver`, `organization`, `assigned_truck`, `current_assignment`, `role`, `locale`, `operational_context` plus flat aliases (`name`, `plate_number`, etc.) |
| `driver_summary` | Compact driver + account identity |
| `counters` | Driver-scoped operational counts (2 aggregate queries) |
| `current_job` | Latest active shipment operational snapshot (nested projections) |
| `quick_actions` | Shortcut metadata (`visible`, `enabled`, `execution`, capabilities) |
| `quick_actions_meta` | `total_visible`, `total_enabled` |
| `notifications_summary` | Unread/critical/assignment/operational counts + capped `items` + `fcm` meta |
| `recent_activity` | Merged timeline (actions, shipments, movements, POD); 5–10 items |
| `timestamps` | `generated_at`, `timezone`, `locale` |
| `generated_at` | Duplicate of `timestamps.generated_at` (legacy-friendly) |

## Settings

| Variable | Default |
|----------|---------|
| `MOBILE_API_DASHBOARD_RECENT_ACTIVITY_LIMIT` | `10` |
| `MOBILE_API_DASHBOARD_SUMMARY_RECENT_ACTIVITY_LIMIT` | `5` |
| `MOBILE_API_DASHBOARD_NOTIFICATION_ITEMS_LIMIT` | `8` |
| `MOBILE_API_DASHBOARD_NOTIFICATION_SUMMARY_ITEMS_LIMIT` | `5` |
| `MOBILE_API_DASHBOARD_NOTIFICATIONS_PUSH_LOOKBACK_DAYS` | `14` |
| `MOBILE_API_DASHBOARD_NOTIFICATIONS_USE_PUSH_RECEIPTS` | `true` |

Performance tuning, indexes, and query budgets: [driver_dashboard_performance.md](./driver_dashboard_performance.md).

## Architecture

```
load_driver_welcome_context()  # assignment+truck+org profile+DriverSettings (minimal columns)
build_dashboard_welcome()      # lightweight projections (no full profile API)
build_dashboard_counters()     # conditional Count aggregates (shipments + movements)
build_current_job_snapshot()
build_recent_activity(limit=N)
build_dashboard_payload(options)
DriverDashboardSerializer
```

### `counters` fields

| Key | Meaning |
|-----|---------|
| `active_shipments` | In-flight shipments for this driver (direct or via booking assignment) |
| `active_movements` | Movement logs in Scheduled / In Progress |
| `pending_pod` | Active shipments where `pod_status` ≠ Compliant |
| `cod_pending` | Active COD shipments with collection still Pending |
| `completed_today` | Delivered/Closed rows updated today |
| `completed_this_week` | Delivered/Closed rows updated since Monday (server TZ) |
| `pending_actions` | `pending_action_shipments` + `active_movements` (no double-count with active_shipments) |

### Counter query budget

- **Shipments:** one `aggregate()` with filtered `Count` columns over `pk__in` driver scope subquery.
- **Movements:** one `aggregate()` with `active_movements` filter.
- No action-log scans, no portal-style per-row loops.

### `welcome` shape (excerpt)

| Block | Fields |
|-------|--------|
| `driver` | `driver_id`, `driver_code`, `name`, `profile_photo_url`, `driver_status`, `driver_type` |
| `organization` | `tenant_id`, `schema_name`, `organization_name`, `company_name`, `logo_url` |
| `assigned_truck` | `truck_id`, `truck_code`, `plate_number`, `truck_status`, `sourcing_mode`, `truck_type_label` |
| `current_assignment` | `assignment_id`, `assigned_from`, `assigned_to`, `assignment_status`, `is_current` |
| `role` | `role_name`, `user_status` |
| `locale` | `request_language`, `supported_languages`, `timezone`, `system_language`, formats |
| `operational_context` | `tenant_schema`, `driver_assignment_required`, `has_assigned_truck`, `has_current_assignment`, `counters_snapshot` |

Flat top-level keys (`driver_id`, `name`, `role_name`, `organization_name`, `assigned_truck`, `plate_number`, …) remain for existing clients.

### `current_job` shape

| Block | Purpose |
|-------|---------|
| `shipment` | `shipment_id`, `shipment_no`, `shipment_status`, `booking_no`, `order_type`, `sourcing_mode`, `shipment_date` |
| `movement` | Active movement for shipment (or latest driver movement) |
| `status` | `shipment_status`, `movement_status`, `operational_stage`, `has_active_movement` |
| `route` | `summary`, `from_label`, `to_label` |
| `truck` | Truck card from shipment |
| `latest_action` | Most recent action log for shipment+driver (1 row) |
| `pod` | `status`, `is_pending`, `needs_attention`, `pod_type` |
| `cod` | `cod_amount`, `collection_status`, `is_cod_order`, `is_collection_pending` |
| `next_action_hint` | Localized workflow hint |

Flat aliases (`shipment_id`, `route_summary`, `pod_status`, …) remain for legacy clients.

### Current job query budget

- **1** `first()` on active shipments (`select_related` truck, booking, addresses).
- **≤2** movement `first()` (shipment-linked, then driver fallback).
- **1** latest action `first()` (`only` + `select_related operation_action`).
- No timeline queries; `recent_activity` is a separate capped list.

### `recent_activity` timeline row

| Field | Description |
|-------|-------------|
| `activity_type` | `action`, `shipment`, `movement`, or `pod` |
| `occurred_at` | ISO timestamp for sorting/display |
| `title` | Localized one-line summary |
| `route_summary` | From/to or `route_display` when shipment context exists |
| `shipment_id` / `movement_id` | Cross-links for drill-down |
| `pod_status` | On shipment/POD rows |
| `log_id` / `log_no` / `log_date` | Populated for `action` rows (legacy-friendly) |

Dedicated endpoint returns `{ "limit": N, "items": [...] }`.

### `quick_actions` (Phase 1 shortcuts)

| `id` | Enabled when | Capability |
|------|----------------|------------|
| `continue_active_job` | `current_job.has_active_job` | `mobile.driver.quick_action.continue_job` |
| `upload_pod` | Active job + POD attention / `pending_pod` counter | `mobile.driver.quick_action.upload_pod` |
| `active_movements` | `counters.active_movements` > 0 | `mobile.driver.quick_action.active_movements` |
| `cod_collection` | `counters.cod_pending` or job COD pending | `mobile.driver.quick_action.cod_collection` |
| `create_empty_move` | Placeholder (disabled, `module_not_available`) | `mobile.driver.quick_action.empty_move` |

Each row includes `execution` (`phase`, `route_key`, `deep_link`, optional `api_path` / `http_method`) for future mobile routing — **no server execution** in Phase 1. Actions without capability are omitted (`visible` flow).

### Activity query budget

Four capped queries (`per_source_cap` = limit, max 10), merge-sort, return top N. No full history.

### `notifications_summary` shape

| Field | Meaning |
|-------|---------|
| `unread_count` | Tenant inbox unread + recent push receipts + ephemeral operational hints |
| `critical_count` | Unread rows with `category=critical` |
| `assignment_count` | Assignment-related unread (inbox + ephemeral) |
| `operational_warnings_count` | POD/COD/ops warnings (inbox + ephemeral) |
| `items` | Capped projections (default 8 full / 5 summary variant) |
| `fcm` | `push_enabled`, `device_token_registered`, deep links (no send) |

**Sources (Phase 1):** `DriverMobileNotification` (tenant inbox), `PushNotificationReceipt` (public, driver-scoped), ephemeral hints from counters/welcome/current job (no DB write on dashboard hit).

## File layout

```
mobile_api/helpers/operational_status.py
mobile_api/helpers/dashboard_aggregations.py
mobile_api/helpers/dashboard_route.py
mobile_api/helpers/dashboard_activity.py
mobile_api/helpers/dashboard_notifications.py
mobile_api/services/driver_dashboard_notifications.py
mobile_api/serializers/driver_dashboard_notifications.py
mobile_api/services/driver_dashboard_quick_actions.py
mobile_api/serializers/driver_dashboard_quick_actions.py
mobile_api/services/driver_dashboard_recent_activity.py
mobile_api/serializers/driver_dashboard_activity.py
mobile_api/services/driver_dashboard_current_job.py
mobile_api/services/driver_dashboard_counters.py
mobile_api/services/driver_dashboard_context.py
mobile_api/services/driver_dashboard_welcome.py
mobile_api/services/driver_dashboard_dto.py
mobile_api/services/driver_dashboard_service.py
mobile_api/serializers/driver_dashboard.py
mobile_api/views/driver_dashboard.py
```
