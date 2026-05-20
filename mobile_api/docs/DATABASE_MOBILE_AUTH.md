# Mobile authentication — database architecture & hardening

This document reviews persistence used by the **driver mobile** login, JWT session validation, password reset / OTP, and related flows. It complements Redis-based JWT controls (blacklist, refresh one-time keys) in `mobile_api.helpers.auth`.

## 1. Multi-tenant placement

| Concern | Storage | Notes |
|--------|---------|--------|
| `TenantUser`, `DriverMaster` | **Per-tenant PostgreSQL schema** (`tenant_*`) | django-tenants; no cross-tenant FKs between subscriber DBs. |
| `DriverPasswordResetOTP` | **Per-tenant schema** (app `mobile_api` is in `TENANT_APPS`) | Table `mobile_api_driver_password_reset_otp`; `tenant_schema` column is denormalized metadata for logs / cross-code clarity — the **connection schema** is still the primary isolation boundary. |
| JWT blacklist, refresh `SET NX`, family invalidation | **Redis** | Not in PostgreSQL; scale horizontally with Redis Cluster / replicas; tune TTLs to token lifetimes. |

**Tenant safety:** All mobile auth SQL for users/drivers must run under `schema_context(schema_name)` (or equivalent middleware) so a connection never reads another subscriber’s rows.

## 2. TenantUser (`tenant_users`)

**Role:** Credential store (`password_hash`), lockout (`login_attempts`, `last_failed_login_at`), session invalidation (`mobile_token_version`), soft-delete (`is_deleted`, `deleted_at`), audit (`last_login_at`, `last_login_ip`).

**Constraints:**

- `email`, `username`, `tenant_ref_no` — **UNIQUE** (per tenant schema). Correct for ERP “one mailbox per workspace user”.
- `mobile_token_version` — integer bump on password change / logout-all; compared to JWT claim on every authenticated request.

**Login hot path (mobile):**

- `TenantUser.all_objects.select_for_update().filter(email__iexact=...)`
- PostgreSQL default `UNIQUE` on `email` is **case-sensitive**. `iexact` may use `UPPER(email) = UPPER(%s)` and **not** use the unique btree as an equality seek.
- **Recommendation (production):** persist **normalized login email** (e.g. `email_normalized` stored lowercased, maintained in `save()`), **unique** on that column, and query with exact match; or use the `citext` extension + `CITEXT` column type.

**Index added:** `(is_deleted, status)` — supports listings and filters that combine soft-delete + activation; low write overhead.

**Optional future indexes** (evaluate under load):

- Partial index active users: `(email) WHERE is_deleted = false` only helps **case-sensitive** equality unless paired with normalized email.
- `(last_failed_login_at)` if you add dashboards on lockouts.

## 3. DriverMaster (`tenant_driver_master`)

**Role:** Links `user_account_id` → `TenantUser` (OneToOne, `on_delete=PROTECT`, **unique**). Mobile session resolution: `DriverMaster.objects.filter(user_account_id=...).select_related('user_account_id')`.

**Indexes:** Existing `driver_status`, `driver_code` indexes support operational UI; FK side on `user_account_id` is covered by the **unique** OneToOne constraint.

**Integrity:** `PROTECT` prevents deleting a `TenantUser` that still has a driver row — good for ERP referential safety.

## 4. OTP table (`mobile_api_driver_password_reset_otp`)

**Access pattern:** `WHERE tenant_schema = ? AND email = ? AND status = ? ORDER BY created_at DESC LIMIT 1` (pending / verified rows).

**Index added:** composite `(tenant_schema, email, status)` — aligns with `get_valid_otp` / `get_verified_otp` and bulk expire-by-email updates.

**Operational hygiene:**

- Rows accumulate (PENDING → EXPIRED / USED). Schedule a **retention job** (e.g. delete `EXPIRED`/`USED` older than 90 days) to keep bloat down.
- Do **not** add a btree on `otp_code` alone — avoids encouraging cross-tenant OTP probing at the SQL layer; keep OTP verification rate-limited at the app layer.

**Security note:** `resolve_tenant_schema_for_otp_with_kind` / `resolve_tenant_schema_for_email_with_kind` iterate registries — **O(tenants)**. **Production default:** `MOBILE_API_PASSWORD_RESET_ALLOW_CROSS_TENANT_DISCOVERY=False` disables these code paths unless an explicit tenant schema is supplied (``X-Tenant-ID`` / ``tenant_id`` / ``request.tenant``). Set the allow flag to ``True`` only for controlled legacy clients.

## 5. JWT “metadata” in PostgreSQL

JWT payload is **not** stored server-side for mobile. DB-backed invalidation relies on:

- `TenantUser.mobile_token_version` (read on each request in `resolve_mobile_driver_session`).
- Redis blacklist + refresh consumption + `rt_fam` invalidation.

**Scalability:** DB read is **one row by PK or FK** per request — cheap. Avoid adding a “sessions” table unless you need server-side device lists; JWT + version is simpler at scale.

## 6. Blacklist storage

**Not in Postgres.** Keys like `mobile:jwt:blacklist:{jti}` in Redis. Plan memory, eviction policy (should not evict before TTL), and HA for production.

## 7. FK & uniqueness checklist

| Item | Status |
|------|--------|
| Driver → user OneToOne + PROTECT | OK |
| Email unique per tenant | OK |
| OTP uniqueness | **Flow-level** “one active PENDING per email” via expiring others — not a DB unique constraint (by design) |

## 8. Migrations shipped in this review

- `mobile_api/migrations/0002_driverpasswordresetotp_composite_index.py` — composite OTP index.
- `tenant_workspace/migrations/0081_tenantuser_auth_listing_index.py` — `(is_deleted, status)` on `TenantUser`.

Apply on all tenant schemas (e.g. `migrate_schemas --tenant` per your django-tenants runbook).

## 9. Further production hardening (optional)

1. **Normalized email** column + unique constraint for login performance and predictable uniqueness under `iexact`.
2. **OTP archival** Celery/cron job by `created_at`.
3. **PgBouncer** in transaction mode: set `DISABLE_SERVER_SIDE_CURSORS` and monitor pool size for mobile spike traffic.
4. **Read replicas:** JWT validation path is read-heavy; route read-only analytics away from primary.
