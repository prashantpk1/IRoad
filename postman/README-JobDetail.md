# Postman — Job Detail Module

## Import

| File | Purpose |
|------|---------|
| `IRoad-Mobile-Driver-JobDetail.postman_collection.json` | All job detail APIs, error flows, smoke tests |
| `IRoad-Mobile-Driver-JobDetail.postman_environment.json` | Local variables (IDs, GPS, cursors) |

Regenerate after API changes:

```bash
python postman/generate_job_detail_postman.py
```

## Quick start

1. Import collection + environment **IRoad Mobile Driver Job Detail — Local**.
2. Set `base_url`, `email`, `password` (driver with `mobile.driver.jobs` + `mobile.driver.jobs.execute`).
3. Run **Setup → Login** (sets `access_token`, `tenant_id`, `driver_id`).
4. Run **00 — Resolve IDs** (sets `shipment_id`, `movement_id` from active lists).
5. Run **08 — Smoke Flows → Flow A** in Collection Runner (read-only).

For mutating tests (execute / POD / COD), use **Flow B** on a **test tenant** only.

## API map

| # | Request | Method | Path | Capability |
|---|---------|--------|------|------------|
| 1 | Shipment job detail | `GET` | `/driver/jobs/shipments/{shipment_id}/` | `mobile.driver.jobs` |
| 2 | Movement job detail | `GET` | `/driver/jobs/movements/{movement_id}/` | `mobile.driver.jobs` |
| 3 | Shipment allowed actions | `GET` | `/driver/jobs/shipments/{shipment_id}/actions/` | `mobile.driver.jobs` |
| 4 | Movement allowed actions | `GET` | `/driver/jobs/movements/{movement_id}/actions/` | `mobile.driver.jobs` |
| 5 | Shipment timeline | `GET` | `/driver/jobs/shipments/{shipment_id}/timeline/` | `mobile.driver.jobs` |
| 6 | Movement timeline | `GET` | `/driver/jobs/movements/{movement_id}/timeline/` | `mobile.driver.jobs` |
| 7 | Shipment execute | `POST` | `/driver/jobs/shipments/{shipment_id}/actions/execute/` | `mobile.driver.jobs.execute` |
| 8 | Movement execute | `POST` | `/driver/jobs/movements/{movement_id}/actions/execute/` | `mobile.driver.jobs.execute` |
| 9 | Upload POD | `POST` | `/driver/jobs/shipments/{shipment_id}/upload-pod/` | `mobile.driver.jobs.execute` |
| 10 | Collect COD | `POST` | `/driver/jobs/shipments/{shipment_id}/collect-cod/` | `mobile.driver.jobs.execute` |

## Headers

| Header | Required | Notes |
|--------|----------|--------|
| `Authorization` | Yes | `Bearer {{access_token}}` |
| `Accept-Language` | No | `{{accept_language}}` — `en` / `ar` |
| `X-Tenant-ID` | No | If set, must match JWT `tenant_schema` |

## JWT automation

- **Login** saves `access_token`, `refresh_token`, `driver_id`, `tenant_id` (when returned).
- Collection-level **Bearer** auth uses `{{access_token}}`.
- Pre-request warns when token is missing.

## Timeline cursor pagination

```
GET .../timeline/?page_size=20
GET .../timeline/?page_size=20&cursor={{timeline_next_cursor}}
```

Page 1 tests auto-save `timeline_next_cursor` from `data.timeline.pagination.next_cursor`.

**Do not** use `page` offset — rejected on job routes.

## Execute / idempotency

Pre-request on mutate folders sets:

- `idempotency_key` → new UUID each run
- `source_ref` → `postman-{timestamp}`

Replay: copy key to `saved_idempotency_key`, run **idempotency replay** request.

## GPS examples (environment)

| Variable | Example |
|----------|---------|
| `sample_latitude` | `24.7136` |
| `sample_longitude` | `46.6753` |
| `sample_map_link` | Google Maps deep link |

## Media upload

- **Execute (multipart):** attach file to `media_file`, set `action_id` from allowed-actions.
- **Upload POD:** attach image to `media_file` (required).

## Error & security folder

| Request | Expected |
|---------|----------|
| No JWT | 401 |
| Wrong `X-Tenant-ID` | 403 tenant_mismatch |
| `foreign_shipment_id` | 404 job_not_found (IDOR) |
| Invalid `action_id` | 400 / 403 |
| Invalid timeline cursor | 400 invalid_cursor |

## Testing scenarios

| Scenario | Folder |
|----------|--------|
| Smoke read path | **08 → Flow A** |
| Execute + workflow refresh | **04** after **02** |
| POD compliance | **05** (shipment at delivery + DN) |
| COD treasury | **06** (COD order pending) |
| RBAC / ownership | **07** |

## Related docs

- `mobile_api/docs/driver_job_detail.md`
- `mobile_api/docs/driver_job_detail_execution.md`
- `mobile_api/docs/driver_job_timeline.md`
- `mobile_api/docs/driver_job_pod_cod.md`
- `mobile_api/docs/driver_job_execution_security.md`
- `mobile_api/docs/driver_job_detail_performance.md`
