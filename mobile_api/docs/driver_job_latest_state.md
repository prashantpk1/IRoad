# Job Detail — Latest state derivation

Authoritative execution state is derived from **append-only action logs**, not only the `shipment_status` column.

## Architecture

```
Action Logs (scoped)
    → latest_action_aggregator (latest + peak impact)
    → execution_stage_deriver (pickup/loading sub-stages + operational label)
    → workflow_state_reconciler (drift vs column cache)
    → LatestStateService (portal + mobile facade)
```

## Modules

| File | Role |
|------|------|
| `latest_action_aggregator.py` | Log scope, latest action summary, peak/latest impact status |
| `execution_stage_deriver.py` | Unified shipment/movement execution sub-stages |
| `workflow_state_reconciler.py` | Drift detection, timeline meta, consistency warnings |
| `services/latest_state_service.py` | Public API + `repair_shipment_column_from_logs()` |

## `execution_state` fields (mobile)

| Field | Meaning |
|-------|---------|
| `authoritative_status` / `derived_status` | Status implied by action log impacts |
| `column_status` / `shipment_status` | DB column cache |
| `execution_sub_stage` | `pickup`, `loading`, `in_transit`, … |
| `operational_stage` | Display label for UI |
| `in_sync` | `false` when drift detected |
| `has_drift` | Shorthand flag |
| `drift` | `{ reason, recommended_column_status, … }` |
| `state_source` | Always `action_logs` |
| `latest_action` | Newest log summary (when reconciler used) |

## Drift reasons

- `column_behind_action_logs` — logs prove further progression than column
- `column_ahead_of_action_logs` — column advanced without matching log evidence
- `early_stage_logs_column_advanced` — pickup/loading logs but column past Loaded

## Repair

`LatestStateService.repair_shipment_column_from_logs(shipment)` calls existing `sync_shipment_status_from_action_log` when drift is detected (portal-safe hybrid sync).

## Policy engine

Allowed actions still come from `get_allowed_actions()`. Reconciled `operational_stage` is **reporting only** and does not change policy membership.
