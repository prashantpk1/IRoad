# Job Detail — Multi-Tenant Deployment & Index Readiness

## Root cause (fixed)

Migration `0093` adds timeline cursor indexes. A broken `0094` previously **removed** those indexes via accidental `RemoveIndex` operations. That is corrected:

- `0094` — field alters only (no index drops)
- `0095` — idempotent `RunPython` ensures all four timeline indexes exist

Model `Meta.indexes` on `TenantOperationActionLog` now matches migrations so `makemigrations` will not regenerate removals.

## Required PostgreSQL indexes

| Index | Purpose |
|-------|---------|
| `tenant_oal_ship_drv_dt_id_idx` | Shipment timeline cursor (`shipment`, `driver`, `-log_date`, `-log_id`) |
| `tenant_oal_move_drv_dt_id_idx` | Movement timeline cursor |
| `tenant_oal_ship_created_idx` | Shipment timeline / created_at paths |
| `tenant_oal_move_created_idx` | Movement created_at paths |
| `tenant_oal_ship_drv_date_idx` | Execution / current-job (0084) |
| `tenant_oal_move_drv_date_idx` | Movement execution (0089) |
| `tenant_oal_channel_idx` | Idempotency channel (0081) |
| `tenant_oal_source_ref_idx` | Source ref (0081) |

Idempotency column: unique `idempotency_key` (0080).

## Deployment-safe migration flow

Run on the app host with production DB credentials (maintenance window optional; indexes are non-concurrent standard `CREATE INDEX`).

```bash
# 1) Audit only (no changes)
python manage.py migrate_job_detail_tenants

# 2) Apply per-tenant migrations (0093 → 0094 → 0095)
python manage.py migrate_job_detail_tenants --apply

# 3) Go-live gate (exit 1 if any schema NOT READY)
python manage.py verify_job_detail_readiness

# Single schema
python manage.py migrate_job_detail_tenants --schema t_your_tenant --apply
python manage.py verify_job_detail_readiness --schema t_your_tenant
```

Equivalent:

```bash
python manage.py validate_job_detail_readiness
```

JSON report for CI:

```bash
python manage.py verify_job_detail_readiness --json
```

## EXPLAIN validation (one tenant)

```bash
python manage.py job_detail_explain_audit \
  --schema t_your_tenant \
  --driver-id <uuid> \
  --page-size 25
```

Expect index scans (or bitmap index scans) on `tenant_operation_action_logs`, not sequential scans at scale.

## Rollback safety

| Migration | Rollback effect |
|-----------|-----------------|
| 0093 | Drops four timeline indexes (only if reversing 0093) |
| 0094 | Field alters only — safe |
| 0095 reverse | Removes timeline indexes **only if present** (idempotent) |

**Production:** prefer forward-only deploy. To roll back indexes, run `migrate tenant_workspace 0092` per tenant only after change approval.

Do **not** re-introduce `RemoveIndex` for timeline indexes in new migrations.

## Production checklist

- [ ] Code includes fixed `0094` + `0095` + model `Meta.indexes`
- [ ] `python manage.py migrate_job_detail_tenants --apply` on all tenant schemas
- [ ] `python manage.py verify_job_detail_readiness` → all **READY**
- [ ] `job_detail_explain_audit` on staging tenant — no seq scan warning
- [ ] Postman Flow A (read/timeline) on staging
- [ ] Optional: `MOBILE_API_RUN_JOB_DETAIL_DB_TESTS=1` integration tests
- [ ] `DEBUG=False`; `MOBILE_API_JOBS_ENFORCE_ACTION_MEMBERSHIP` not used to bypass in prod

## Tenant-by-tenant verification

```bash
python manage.py verify_job_detail_readiness --schema t_abc --json
```

Each schema report includes:

- `missing_migrations`
- `missing_timeline_indexes`
- `missing_execution_indexes`
- `middleware_ok`

## CI integration

```yaml
- run: python manage.py verify_job_detail_readiness --json
```

Fail the pipeline on non-zero exit when any tenant is NOT READY.
