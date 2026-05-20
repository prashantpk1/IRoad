# Mobile API RBAC

## Layers

1. **Authentication** (`MobileJWTAuthentication` + `resolve_mobile_driver_session`)  
   Validates JWT, tenant, active `DriverMaster` for **driver-issued** tokens.

2. **Authorization** (DRF `permission_classes`)  
   Role gates: `IsDriver`, `IsDispatcher`, `IsTenantAdmin`.  
   Capability gate: `HasViewMobileCapability` reads `required_mobile_capability` on the view.

3. **Capability matrix** (`mobile_api/rbac.CAPABILITY_GROUPS`)  
   Maps stable ids (e.g. `mobile.operations.read`) → role groups (`driver`, `dispatcher`, `tenant_admin`).

4. **Runtime extension**  
   `register_mobile_capability(capability_id, ('dispatcher',))` from `AppConfig.ready` in other apps.

## Settings (CSV, case-insensitive)

| Setting | Purpose |
|--------|---------|
| `MOBILE_API_RBAC_DRIVER_ROLE_NAMES` | Overrides default driver role names; unioned with `MOBILE_API_DRIVER_ROLE_ALLOWLIST`. |
| `MOBILE_API_RBAC_DISPATCHER_ROLE_NAMES` | Dispatcher operational roles (defaults apply if unset). |
| `MOBILE_API_RBAC_TENANT_ADMIN_ROLE_NAMES` | Tenant admin roles; also drives JWT `is_admin` at login. |

## JWT claims

- `tenant_schema`, `role_name`, `driver_id`, `is_admin` (boolean from tenant-admin role list). Authenticated driver routes resolve the subscriber from `tenant_schema` unless an optional `X-Tenant-ID` / body hint is sent (it must match the token).

## Non-DRF views

Use `mobile_api.decorators.mobile_capability_required('mobile.operations.read')`.

## Operational stub

`GET /api/v1/mobile/operational/health/` requires capability `mobile.operations.read` (dispatcher or tenant admin).
