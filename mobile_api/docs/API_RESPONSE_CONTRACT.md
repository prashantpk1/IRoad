# Mobile API — unified response contract (`v1`)

All JSON responses from `/api/v1/mobile/` share one envelope. HTTP status codes follow REST semantics; the body field **`status`** is the **application** outcome for mobile clients.

## Envelope

| Field | Type | Description |
|--------|------|-------------|
| `status` | `1` \| `0` \| `2` | **1** success, **0** recoverable/business error, **2** auth/session failure |
| `message` | string | Human-readable text (resolved using `Accept-Language` / `X-Language`) |
| `message_key` | string? | Optional **gettext msgid** (e.g. `mobile.auth.login_success`) for client-side catalogs |
| `data` | object | Success payload **or** structured error payload |
| `meta` | object | Correlation, locale, contract version |

### `meta`

| Field | Description |
|--------|-------------|
| `request_id` | UUID, or client `X-Request-ID` / `X-Correlation-ID` when sent |
| `timestamp` | ISO-8601 UTC (`…Z`) |
| `locale` | Active language code |
| `api_version` | Contract string from `MOBILE_API_CONTRACT_VERSION` (default `1.0`) |

## Success (`status` 1)

```json
{
  "status": 1,
  "message": "Login successful",
  "message_key": "mobile.auth.login_success",
  "data": { "access_token": "…" },
  "meta": { "request_id": "…", "timestamp": "…", "locale": "en", "api_version": "1.0" }
}
```

## Business / validation error (`status` 0)

HTTP **4xx** (except auth) or **5xx** as appropriate.

```json
{
  "status": 0,
  "message": "Validation failed",
  "message_key": "mobile.validation.failed",
  "data": {
    "error": { "code": "validation_failed", "details": {} },
    "error_code": "validation_failed",
    "validation": {
      "fields": {
        "email": [{ "message": "Enter a valid email address.", "code": "invalid" }]
      }
    },
    "errors": { "email": "Enter a valid email address." }
  },
  "meta": { … }
}
```

- **`data.error`** — canonical machine-readable block (`code` + optional `details`).
- **`data.error_code`** — duplicate of `data.error.code` for legacy clients.
- **`data.validation.fields`** — structured field errors.
- **`data.errors`** — flat map *field → first message* for legacy UIs.

## Auth / session error (`status` 2)

HTTP **401** or **403** as appropriate (invalid token, permission denied).

```json
{
  "status": 2,
  "message": "Unauthorized",
  "message_key": "mobile.auth.unauthorized",
  "data": {
    "error": { "code": "unauthorized", "details": {} },
    "error_code": "unauthorized"
  },
  "meta": { … }
}
```

## HTTP status ↔ `status` (quick reference)

| HTTP | Body `status` | Typical `data.error.code` |
|------|----------------|----------------------------|
| 200 | 1 | — |
| 400 | 0 | `validation_failed`, `invalid_tenant`, … |
| 401 | 0 or 2 | Wrong password → `0` + `invalid_credentials`; missing JWT → `2` + `unauthorized` |
| 403 | 0 or 2 | `tenant_mismatch`, `forbidden` |
| 404 | 0 | `not_found` |
| 409 | 0 | `tenant_ambiguous`, `tenant_ambiguous_operation` |
| 429 | 0 | `rate_limited` |
| 500 | 0 | `server_error` |

## Client guidance

1. Prefer **`data.error.code`** (and **`message_key`**) for branching; use **`message`** for display fallback.
2. Send **`X-Request-ID`** from the app to tie logs to support tickets.
3. Keep a local string table keyed by **`message_key`** when you ship offline translations.
