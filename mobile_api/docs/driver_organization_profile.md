# Driver Organization Profile (mobile API)

Lightweight notes for **`GET /api/v1/mobile/driver/organization-profile/`**.

## Endpoint

- **Method:** `GET`
- **Path:** `/api/v1/mobile/driver/organization-profile/` (under global `/api/v1/mobile/` prefix)
- **Route name:** `mobile_api:driver_organization_profile`

## Authentication

- **Required:** `Authorization: Bearer <access_token>` (same JWT flow as other driver routes).
- Without a valid token, expect **`status: 2`** and **HTTP 401** (mobile API convention).

## Tenant

- **Primary:** the access JWT carries **`tenant_schema`**; the server uses it for authenticated driver routes (same as profile, logout, and so on).
- **Optional:** send **`X-Tenant-ID`** only if you supply an explicit subscriber hint; it **must match** the JWT `tenant_schema` when both are present.

## Localization (`Accept-Language`)

- Optional header; first tag should be **`en`** or **`ar`** (two-letter).
- Affects **`data.organization_name`** only: resolved from model **`name_en`** / **`name_ar`** with empty-side fallback (same helpers as other mobile localized fields).
- **`data.driver_instructions`** is a **single** database column: the API returns the **same** string for **`en`**, **`ar`**, or missing header. It may contain HTML (e.g. from tenant CMS). There are no `_en` / `_ar` instruction fields.

## Media

- **`data.logo_url`**: absolute URL when an organization logo file exists; otherwise an **empty string** (`""`). Clients should treat empty string as “no logo”.

## Success envelope

```json
{
  "status": 1,
  "message": "<translated success string>",
  "data": {
    "organization_name": "",
    "support_email": "",
    "support_mobile_number_1": "",
    "support_mobile_number_2": "",
    "driver_instructions": "",
    "logo_url": ""
  }
}
```

## Errors

- Driver / user validation failures: **`status: 0`**, **`message`** from auth/profile guard strings (e.g. inactive driver).
- No `OrganizationProfile` row for tenant: **`status: 0`**, not-found style message.
- See implementation: `mobile_api/views/driver_organization_profile.py`, `mobile_api/services/driver_organization_profile_service.py`, `mobile_api/serializers/driver_organization_profile.py`.
