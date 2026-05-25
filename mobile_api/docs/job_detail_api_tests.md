# Job Detail API security tests (JWT + tenant isolation)

Real `APITestCase`-style HTTP tests against PostgreSQL tenant schemas (no mocked
`MobileJWTAuthentication` or permission classes).

## Run

```powershell
$env:MOBILE_API_JOB_DETAIL_TEST_USE_DEV_DB='1'
# Optional: tenant with TenantRegistry + linked driver user
$env:MOBILE_API_JOB_DETAIL_TEST_SCHEMA='t_e0fd39d3fd3f4b7794c911e52ace9b41'

python manage.py test mobile_api.tests.test_job_detail_api_security --keepdb
```

## Coverage (`test_job_detail_api_security.py`)

| Area | Cases |
|------|--------|
| JWT | missing Bearer (403), malformed/expired/wrong `driver_id` claim (401), valid auth |
| Tenant | `X-Tenant-ID` mismatch (403), jobs middleware `tenant_mismatch` |
| RBAC | non-driver JWT (no `driver_id`) denied on read/execute/movement |
| Ownership | foreign shipment/movement/timeline/actions → 404; cross-driver |
| Execute | foreign job 404, unknown `action_id` → 400, POST not 405 |

## Helpers

`mobile_api/tests/job_detail_api_support.py` — `generate_access_token` /
`build_token_claims`, fixture seeding, `APIClient` headers.
