# Mobile API RBAC

## Layers

1. **Authentication** (`MobileJWTAuthentication` + `resolve_mobile_driver_session`)  
   Validates JWT, tenant, active `DriverMaster` for driver-issued tokens.

2. **Authorization** (DRF `permission_classes`)  
   Role gates: `IsDriver`, `IsDispatcher`, `IsTenantAdmin`.  
   Capability gate: `HasViewMobileCapability` reads `required_mobile_capability` on the view.

3. **Capability matrix** (`mobile_api/rbac.CAPABILITY_GROUPS`)  
   Maps stable ids, such as `mobile.operations.read`, to role groups (`driver`, `dispatcher`, `tenant_admin`).

4. **Runtime extension**  
   `register_mobile_capability(capability_id, ('dispatcher',))` from `AppConfig.ready` in other apps.

## Settings

| Setting | Purpose |
|--------|---------|
| `MOBILE_API_RBAC_DRIVER_ROLE_NAMES` | Overrides default driver role names; unioned with `MOBILE_API_DRIVER_ROLE_ALLOWLIST`. |
| `MOBILE_API_RBAC_DISPATCHER_ROLE_NAMES` | Dispatcher operational roles. |
| `MOBILE_API_RBAC_TENANT_ADMIN_ROLE_NAMES` | Tenant admin roles; also drives JWT `is_admin` at login. |

## JWT Claims

- `tenant_schema`
- `role_name`
- `driver_id`
- `is_admin`

Authenticated driver routes resolve the subscriber from `tenant_schema`. Any optional `X-Tenant-ID` or body tenant hint must match the token.

## Remaining Mobile Capabilities

| Capability | Role | API surface |
|------------|------|-------------|
| `mobile.driver.profile` | `driver` | Driver profile APIs |
| `mobile.driver.organization` | `driver` | Organization profile API |
| `mobile.driver.history` | `driver` | Driver History list + detail (read-only) |
| `mobile.driver.auth_session` | `driver` | Authenticated driver session operations |
| `mobile.operations.read` | `dispatcher`, `tenant_admin` | `GET /api/v1/mobile/operational/health/` |
| `mobile.operations.write` | `dispatcher`, `tenant_admin` | Reserved for future operational mobile APIs |
| `mobile.tenant.admin` | `tenant_admin` | Reserved for tenant administration |

## Non-DRF Views

Use `mobile_api.decorators.mobile_capability_required('mobile.operations.read')`.
