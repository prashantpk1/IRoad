# Mobile API — production security checklist

This document complements code in `config/settings.py`, `mobile_api/helpers/auth.py`, `mobile_api/middleware.py`, `mobile_api/throttling.py`, and `mobile_api/checks.py`.

**Environment matrix:** see `mobile_api/docs/MOBILE_AUTH_ENV_REQUIRED.md`.

## Transport and cookies

- [ ] Terminate TLS at a reverse proxy and set `SECURE_PROXY_SSL_HEADER` (already `(HTTP_X_FORWARDED_PROTO, https)`).
- [ ] Set `SECURE_SSL_REDIRECT=True` when Django serves HTTP directly in production (often **False** when TLS is only at the proxy).
- [ ] Set `SESSION_COOKIE_SECURE=True` and `CSRF_COOKIE_SECURE=True` when the site is HTTPS-only.
- [ ] Set `ALLOWED_HOSTS` to explicit hostnames (comma-separated). Avoid `*` in production.
- [ ] Tune `SECURE_HSTS_SECONDS` (e.g. `31536000`) once you are confident all clients use HTTPS.

## CORS (browser / WebView clients)

- [ ] Set `DEBUG=False` in production **or** explicitly set `CORS_ALLOW_ALL_ORIGINS=False`.
- [ ] Set `CORS_ALLOWED_ORIGINS` to a comma-separated list of exact `https://…` origins for any web or hybrid clients.
- [ ] Never rely on `CORS_ALLOW_ALL_ORIGINS=True` with `CORS_ALLOW_CREDENTIALS=True` outside local development.

## Redis and JWT

- [ ] Run a dedicated Redis for session/JWT support with persistence and monitoring.
- [ ] Set `MOBILE_API_REFRESH_REQUIRE_REDIS=True` in production so refresh rotation cannot proceed without Redis.
- [ ] Set `MOBILE_API_JWT_DENY_ON_REDIS_READ_ERROR=True` when availability trade-offs favor **deny** on blacklist/family read failures (fail closed).
- [ ] `MOBILE_API_REFRESH_CONSUME_FAIL_CLOSED_ON_REDIS_ERROR` defaults to **True**: Redis errors during refresh `SET NX` deny rotation (mitigates replay if blacklist write lagged).
- [ ] Set `MOBILE_API_JWT_ISS` and `MOBILE_API_JWT_AUD` to non-empty values so issued tokens are bound to your deployment.
- [ ] Use a long random `MOBILE_API_JWT_SIGNING_KEY` distinct from `SECRET_KEY`.

## Rate limits and abuse

- [ ] Tune `REST_FRAMEWORK` `DEFAULT_THROTTLE_RATES` keys: `mobile_login`, `mobile_auth`, `mobile_forgot_password`, `mobile_verify_otp`, `mobile_reset_password`.
- [ ] Tune cache-backed burst limits: `MOBILE_API_LOGIN_BURST_*` and password-reset keys under `MOBILE_API_PASSWORD_RESET_*`.
- [ ] Ensure Django `CACHES` points to Redis (or another shared store) in multi-worker deployments so limits are global.

## Application behaviour

- [ ] Keep `MOBILE_API_PASSWORD_RESET_ALLOW_CROSS_TENANT_DISCOVERY=False` (default) in production.
- [ ] Keep `MOBILE_API_JWT_REQUIRE_TENANT_HINT=True` and `MOBILE_API_AUTH_ENDPOINTS_REQUIRE_TENANT_HINT=True` unless you have a controlled reason to relax them. With JWT tenant claims, authenticated mobile calls do **not** need `X-Tenant-ID` on every request; optional hints must match the token.
- [ ] `MOBILE_API_LOGIN_REQUIRE_EXPLICIT_TENANT` defaults to **True** when `DEBUG=False`, which disables scanning all tenants for login credentials; set explicitly for staging if you still need auto tenant discovery during migration. Login still accepts optional JSON `tenant_id` for disambiguation when the same credentials exist on multiple tenants.

## Response headers

- [ ] `MobileApiSecurityHeadersMiddleware` adds `Cache-Control: no-store`, `Permissions-Policy`, and related headers for `/api/v1/mobile/`. Disable with `MOBILE_API_SECURITY_HEADERS_ENABLED=False` only if a proxy adds equivalent headers.

## Verification

- [ ] Run `python manage.py check --deploy` before release.
- [ ] Load-test login and refresh under Redis failure and confirm policy (deny vs allow) matches your SLO.
