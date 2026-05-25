# Job list — latest action & next action

Batched operational progression on job cards (no per-row log queries).

## Query budget (per paginated list request)

| Step | Queries | Notes |
|------|---------|-------|
| List queryset | 1 | Includes `latest_action_log_id` **Subquery** annotation |
| Page hydrate | 1 | `log_id__in` bulk fetch + `select_related(operation_action)` |
| Next-action hints | 0 | Pure field logic on loaded rows |
| Card build | 0 | Reads cached attrs on each row |

**Never** call `fetch_latest_action_log()` inside list loops.

## Modules

| Module | Role |
|--------|------|
| `job_list_action_aggregation.py` | Subquery annotate, bulk fetch, page hydrate |
| `job_list_next_action.py` | Shipment/movement hint builders (no ORM) |
| `job_card_projections.py` | `resolve_*_for_job_card` reads hydrated attrs |
| `driver_jobs._paginate_job_cards` | Calls `hydrate_job_list_page_actions` after pagination |

## Latest action projection

```json
{
  "log_id": "uuid",
  "log_no": "OAL-001",
  "log_date": "2026-05-21T10:00:00+00:00",
  "action_code": "DEPART",
  "action_label": "Departed"
}
```

- **Shipments:** latest log where `shipment_id` + `driver_id` (index `tenant_oal_ship_drv_date_idx`)
- **Movements:** latest log where `truck_movement_id` + `driver_id` (index `tenant_oal_move_drv_date_idx`)

## Next action hint

- **Shipment cards:** POD → COD → status-based hints (same rules as dashboard `build_next_action_hint`)
- **Movement cards:** linked shipment hint when prefetched; else movement status hint (Scheduled / In Progress)

## Toggle

| Source | Default |
|--------|---------|
| `MOBILE_JOB_LIST_INCLUDE_ACTIONS` | `True` |
| Query `include_actions=0` | Disables log fetch + annotations; hints still computed |

Response `meta.include_actions` echoes the effective flag.

## Migration

```bash
python manage.py migrate tenant_workspace 0089
```

Adds `tenant_oal_move_drv_date_idx` for movement list latest-action subqueries.
