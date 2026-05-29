# Driver History API — Postman Setup

## Import

1. Postman → **Import**
2. Select:
   - `Iroad_Mobile_Driver_History.postman_collection.json`
   - `Iroad_Mobile_Local.postman_environment.json` (shared with Job Detail / Dashboard)
3. Choose environment **Iroad Mobile — Local**

## Variables

| Variable | Purpose |
|----------|---------|
| `base_url` | `http://127.0.0.1:8000/api/v1/mobile` |
| `driver_email` / `driver_password` | Test driver credentials |
| `access_token` | Set by login |
| `tenant_schema` | Set by login (`organization.schema_name`) |
| `shipment_id` | Auto-set from first history list item |
| `history_filter_shipment_no` | Filter popup — e.g. `SH-2026-1001` |
| `history_filter_date` | Filter popup — `DD-MM-YYYY` or `YYYY-MM-DD` |

## Recommended run order (matches `postman/IRoute_History_Flow_Collection.json`)

| Step | Request |
|------|---------|
| 1 | **01 — Login** |
| 2 | **02 — History List** (all completed jobs) |
| 3 | **03 — Filter Preview** (`count_only=true`) |
| 4 | **04 — Apply Filter** |
| 5 | **05 — History Detail** |

## Endpoints (app needs only these 3)

| Screen | Method | URL |
|--------|--------|-----|
| History list | GET | `{{base_url}}/driver/history/` |
| Filter count / apply | GET | `{{base_url}}/driver/history/?count_only=true&...` or same without `count_only` |
| History detail | GET | `{{base_url}}/driver/history/{{shipment_id}}/` |

No separate pagination or duplicate detail request — list returns all matches; detail uses `shipment_id` from the card.

## Prerequisites

- Django running: `python manage.py runserver`
- Driver has at least one shipment in status **Closed** or **Cancelled**
- Capability `mobile.driver.history` (driver role)

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Empty `items` | No terminal shipments for this driver — complete a job (A10) first |
| `history_not_available` on detail | Shipment still active — use Job Detail, not History |
| 401 | Run login or paste `access_token` |
| 403 tenant_mismatch | Remove `X-Tenant-ID` or align with JWT `tenant_schema` |
