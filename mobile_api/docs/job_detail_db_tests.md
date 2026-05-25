# Job Detail — PostgreSQL DB E2E Tests

## When tests run

Tests run automatically when:

- Database vendor is **PostgreSQL**, and
- At least one tenant schema is **Job Detail READY** (`verify_job_detail_readiness`), and
- `MOBILE_API_SKIP_JOB_DETAIL_DB_TESTS` is not set

Force on: `MOBILE_API_RUN_JOB_DETAIL_DB_TESTS=1`  
Pin schema: `MOBILE_API_JOB_DETAIL_TEST_SCHEMA=t_your_tenant`  
**Use dev DB (required for `manage.py test`):** `MOBILE_API_JOB_DETAIL_TEST_USE_DEV_DB=1`

## Prerequisites

```bash
python manage.py migrate_job_detail_tenants --apply
python manage.py verify_job_detail_readiness
```

## Run suite

Django’s default `test_*` clone has no tenant migrations. Point tests at your dev DB:

```powershell
$env:MOBILE_API_JOB_DETAIL_TEST_USE_DEV_DB='1'
$env:MOBILE_API_JOB_DETAIL_TEST_SCHEMA='t_your_tenant'   # optional
```

```bash
python manage.py test mobile_api.tests.test_job_detail_db_integration
python manage.py test mobile_api.tests.test_job_detail_db_execution
python manage.py test mobile_api.tests.test_job_detail_db_pod_cod
python manage.py test mobile_api.tests.test_job_detail_readiness
```

All Job Detail DB modules:

```bash
python manage.py test mobile_api.tests.test_job_detail_db_integration mobile_api.tests.test_job_detail_db_execution mobile_api.tests.test_job_detail_db_action_execution mobile_api.tests.test_job_detail_db_pod_cod mobile_api.tests.test_job_detail_db_rollback mobile_api.tests.test_job_detail_db_concurrency --keepdb
```

Concurrency-only:

```bash
python manage.py test mobile_api.tests.test_job_detail_db_concurrency --keepdb
```

Skipped tests mean no allowed action for the fixture shipment/movement in Action Master — seed operational data or set `MOBILE_API_JOB_DETAIL_TEST_SCHEMA` to a busy tenant.

## Coverage map

| Module | Covers |
|--------|--------|
| `test_job_detail_db_integration` | Timeline cursor, scoped queries, allowed actions, indexes |
| `test_job_detail_db_execution` | Shipment/movement execute, idempotency, duplicate guard, rollback, row locks, threading |
| `test_job_detail_db_pod_cod` | POD + COD real execution (skips if Action Master / compliance not met) |
| `test_job_detail_db_rollback` | Side-effect, media, IntegrityError, POD/COD, shipment/movement status rollback proofs |
| `test_job_detail_db_concurrency` | Threaded parallel execute, idempotency races, row locks, POD/COD, timeline + execute |

## Shared fixtures

`mobile_api/tests/job_detail_db_support.py` — `JobDetailDbTestBase` with real tenant schema, driver, shipment, movement, and `SecureJobExecutionContext`.
