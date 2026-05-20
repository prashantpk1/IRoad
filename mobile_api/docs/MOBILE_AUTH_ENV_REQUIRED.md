# Mobile authentication — required environment variables

Use this list when promoting **staging** or **production**. Values are read via `python-decouple` from `.env` or the process environment.

## Core Django

| Variable | Production | Notes |
|----------|------------|--------|
| `DEBUG` | `False` | Enables strict defaults for mobile JWT, CORS checks, and HTTPS-related settings. |
| `SECRET_KEY` | (required) | Django secret; **not** a substitute for `MOBILE_API_JWT_SIGNING_KEY` in production. |
| `ALLOWED_HOSTS` | Comma-separated hostnames | Never `*` in production. `manage.py check --deploy` warns via `mobile_api.W020`. |

## HTTPS / cookies (defaults strict when `DEBUG=False`)

| Variable | Typical production | Notes |
|----------|-------------------|--------|
| `SECURE_SSL_REDIRECT` | `True` or `False` | `True` if Django terminates HTTP. Often `False` when TLS is only at the reverse proxy (keep `SECURE_PROXY_SSL_HEADER`). |
| `SESSION_COOKIE_SECURE` | `True` | |
| `CSRF_COOKIE_SECURE` | `True` | |
| `SECURE_HSTS_SECONDS` | `31536000` | Default when `DEBUG=False` in `settings.py`. Override if needed before enabling HSTS. |

## CORS (browser / WebView clients)

| Variable | Production | Notes |
|----------|------------|--------|
| `CORS_ALLOW_ALL_ORIGINS` | `False` | **Required** when `DEBUG=False` (`mobile_api.E010`). |
| `CORS_ALLOWED_ORIGINS` | Comma-separated `https://…` | Empty list warns (`mobile_api.W011`). |

## Redis

Production mobile JWT revocation and refresh rotation depend on Redis (via `superadmin.redis_helpers` and Django `CACHES`).

- Run Redis with persistence/monitoring appropriate to your SLO.
- When `MOBILE_API_JWT_DENY_ON_REDIS_READ_ERROR=True`, a Redis read outage causes **valid-looking** tokens to be rejected if blacklist/family state cannot be read (fail closed).

## Mobile JWT (mandatory when `DEBUG=False`)

| Variable | Production | Notes |
|----------|------------|--------|
| `MOBILE_API_JWT_SIGNING_KEY` | Long random string, **≥** `MOBILE_API_JWT_SIGNING_KEY_MIN_LENGTH` (default 32) | Required when `DEBUG=False` (`mobile_api.E003`). |
| `MOBILE_API_JWT_ISS` | Non-empty stable issuer URI/string | Required when `DEBUG=False` (`mobile_api.E001`). |
| `MOBILE_API_JWT_AUD` | Non-empty audience string | Required when `DEBUG=False` (`mobile_api.E002`). |
| `MOBILE_API_JWT_LEEWAY_SECONDS` | e.g. `30` | Clock skew tolerance for `exp` verification. |
| `MOBILE_API_JWT_REQUIRE_IAT_CLAIM` | `True` (default when `DEBUG=False`) | Decode requires `iat`. |
| `MOBILE_API_JWT_DENY_ON_REDIS_READ_ERROR` | `True` (default when `DEBUG=False`) | Fail closed on Redis read errors for blacklist / family invalidation. Warns if `False` (`mobile_api.W004`). |
| `MOBILE_API_REFRESH_REQUIRE_REDIS` | `True` (default when `DEBUG=False`) | Refresh rotation denied without Redis. Warns if `False` (`mobile_api.W005`). |
| `MOBILE_API_REFRESH_CONSUME_FAIL_CLOSED_ON_REDIS_ERROR` | `True` | Default in settings; keep for replay safety. |

## Tenant safety

| Variable | Recommended production | Notes |
|----------|------------------------|--------|
| `MOBILE_API_JWT_REQUIRE_TENANT_HINT` | `True` | A resolvable tenant context is still required, but for **Bearer** requests the JWT’s `tenant_schema` satisfies this (no `X-Tenant-ID` on every call). Optional header/body tenant must match the token when sent. |
| `MOBILE_API_AUTH_ENDPOINTS_REQUIRE_TENANT_HINT` | `True` | Forgot / verify / reset require tenant context. |
| `MOBILE_API_LOGIN_REQUIRE_EXPLICIT_TENANT` | `True` (default when `DEBUG=False`) | Disables credential-based tenant scanning on login. |
| `MOBILE_API_PASSWORD_RESET_ALLOW_CROSS_TENANT_DISCOVERY` | `False` (default) | When `False`, no cross-schema email/OTP discovery in services. Warns if `True` in prod (`mobile_api.W030`). |

## Abuse limits (optional tuning)

| Prefix | Purpose |
|--------|---------|
| `MOBILE_API_LOGIN_MAX_ATTEMPTS` / `MOBILE_API_LOGIN_LOCKOUT_MINUTES` | Per-row DB lockout. |
| `MOBILE_API_LOGIN_BURST_*` | Cache burst limits; `MOBILE_API_LOGIN_BURST_FAIL_CLOSED_ON_CACHE_ERROR` fail-closed on cache read errors (default strict when `DEBUG=False`). |
| `MOBILE_API_PASSWORD_RESET_*` | OTP expiry, attempts, resend cooldown, rate windows; `MOBILE_API_PASSWORD_RESET_RATE_FAIL_CLOSED_ON_CACHE_ERROR` for OTP rate counters. |

## Verification commands

```bash
python manage.py check
python manage.py check --deploy
```

Deploy checks register `mobile_api` security IDs `E001`–`E010`, `W004`–`W005`, `W011`, `W020`, `W030`.

## Security logging

Structured security events use the logger name **`mobile_api.security`** (see `mobile_api.helpers.security_audit`). Route it in your central logging stack for SOC review.
