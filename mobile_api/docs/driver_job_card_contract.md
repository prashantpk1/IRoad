# Driver job card contract (mobile list)

Phase 1 unified projection: `mobile_api/helpers/job_card_projections.py`

## Design principles

- **Flat first** — mobile list UIs read top-level fields.
- **No portal serializers** — ORM rows → dict projections only.
- **Latest action** — batched per page via subquery + bulk fetch (see [driver_job_list_actions.md](./driver_job_list_actions.md)).
- **Optional nests** — `route`, `truck`, `indicators` mirror flat data (no extra queries).

## Unified fields (`JobCardSerializer`)

| Field | Description |
|-------|-------------|
| `job_id` | UUID primary key |
| `job_type` | `shipment` \| `movement` |
| `job_no` | `shipment_no` or `movement_no` |
| `current_status` | Operational status label |
| `route_summary` | Human route string |
| `from_location` / `to_location` | Endpoint labels |
| `truck_id`, `truck_code`, `plate_number`, `truck_status`, `truck_sourcing_mode` | Flat truck snapshot |
| `latest_action_summary` | `{ log_id, log_no, log_date, action_code, action_label }` or `null` |
| `next_action_hint` | Shipment-only hint string or `null` |
| `pod_status`, `cod_status`, `collection_status` | Shipment POD/COD (empty on movements) |
| `needs_pod`, `needs_cod`, `is_active`, `is_empty_move` | Flat indicators |
| `is_pod_pending`, `is_cod_pending`, `is_cod_order` | Shipment convenience flags |
| `updated_at`, `created_at` | ISO-8601 strings |

## Shipment extensions

`shipment_id`, `shipment_no`, `booking_no`, `order_type`, `shipment_date`

## Movement extensions

`movement_id`, `movement_no`, `movement_source`, `empty_move_reason`, `movement_date`, linked `shipment_id` / `shipment_no`

## Builders

| Function | Use |
|----------|-----|
| `build_shipment_job_card_projection()` | Service + tests |
| `build_movement_job_card_projection()` | Service + tests |
| `build_shipment_job_card()` | Thin wrapper in shipment list service |
| `build_movement_job_card()` | Thin wrapper in movement list service |

## Serializers

- `JobCardSerializer` — shared envelope
- `ShipmentJobCardSerializer` — extends base
- `MovementJobCardSerializer` — extends base
