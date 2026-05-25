"""
JWT + APIClient helpers for Job Detail APITestCase security suites.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from django.db import connection

from mobile_api.helpers.auth import (
    ALGORITHM,
    TOKEN_TYPE_ACCESS,
    _get_signing_key,
    _registered_claims_iss_aud,
    generate_access_token,
)
from mobile_api.helpers.job_detail_readiness import (
    any_job_detail_ready,
    audit_job_detail_schemas,
)
from mobile_api.helpers.job_list_readiness import list_tenant_schemas
from mobile_api.helpers.mobile_tenant import resolve_active_tenant_registry
from mobile_api.services.driver_auth_service import (
    build_token_claims,
    get_driver_master_by_user,
)


def job_detail_api_use_dev_database() -> bool:
    return os.environ.get('MOBILE_API_JOB_DETAIL_TEST_USE_DEV_DB', '').strip().lower() in (
        '1',
        'true',
        'yes',
    )


def _connection_is_ephemeral_test_db() -> bool:
    name = (connection.settings_dict.get('NAME') or '').strip()
    return name.startswith('test_')


def job_detail_api_tests_enabled() -> bool:
    if connection.vendor != 'postgresql':
        return False
    if os.environ.get('MOBILE_API_SKIP_JOB_DETAIL_API_TESTS', '').strip().lower() in (
        '1',
        'true',
        'yes',
    ):
        return False
    if os.environ.get('MOBILE_API_SKIP_JOB_DETAIL_DB_TESTS', '').strip().lower() in (
        '1',
        'true',
        'yes',
    ):
        return False
    if _connection_is_ephemeral_test_db() and not job_detail_api_use_dev_database():
        return False
    force = os.environ.get('MOBILE_API_RUN_JOB_DETAIL_API_TESTS', '').strip().lower() in (
        '1',
        'true',
        'yes',
    )
    if force or job_detail_api_use_dev_database():
        if any_job_detail_ready(audit_job_detail_schemas()):
            return True
        return _any_schema_has_linkable_driver()
    return any_job_detail_ready(audit_job_detail_schemas())


def _any_schema_has_linkable_driver() -> bool:
    explicit = (os.environ.get('MOBILE_API_JOB_DETAIL_TEST_SCHEMA') or '').strip()
    if explicit and _schema_has_linked_driver(explicit):
        return True
    try:
        from iroad_tenants.models import TenantRegistry

        for reg in TenantRegistry.objects.order_by('schema_name'):
            if _schema_has_linked_driver(str(reg.schema_name).strip()):
                return True
    except Exception:
        pass
    for name in list_tenant_schemas()[:80]:
        if _schema_has_linked_driver(name):
            return True
    return False


def api_skip_reason() -> str:
    if not job_detail_api_tests_enabled():
        return (
            'Set MOBILE_API_JOB_DETAIL_TEST_USE_DEV_DB=1 and ensure Job Detail READY schema'
        )
    return ''


def _schema_has_linked_driver(schema: str) -> bool:
    from django_tenants.utils import schema_context

    from tenant_workspace.models import DriverMaster, TenantUser

    with schema_context(schema):
        for candidate in DriverMaster.objects.filter(
            driver_status=DriverMaster.Status.ACTIVE,
        ).select_related('user_account_id')[:20]:
            tu = candidate.user_account_id
            if tu is None or tu.is_deleted:
                continue
            if tu.status == TenantUser.Status.ACTIVE:
                return True
        driver = DriverMaster.objects.filter(
            driver_status=DriverMaster.Status.ACTIVE,
        ).first()
        user = TenantUser.objects.filter(
            is_deleted=False,
            status=TenantUser.Status.ACTIVE,
        ).first()
        return driver is not None and user is not None


def pick_api_schema() -> str | None:
    explicit = (os.environ.get('MOBILE_API_JOB_DETAIL_TEST_SCHEMA') or '').strip()
    if explicit:
        return explicit
    try:
        from iroad_tenants.models import TenantRegistry

        for reg in TenantRegistry.objects.order_by('schema_name'):
            schema = str(reg.schema_name).strip()
            if schema and _schema_has_linked_driver(schema):
                return schema
        for reg in TenantRegistry.objects.order_by('schema_name'):
            schema = str(reg.schema_name).strip()
            if not schema:
                continue
            reports = audit_job_detail_schemas(schemas=[schema])
            if reports and reports[0].ready and _schema_has_linked_driver(schema):
                return schema
    except Exception:
        pass
    for report in audit_job_detail_schemas():
        if report.ready and _schema_has_linked_driver(report.schema):
            return report.schema
    for report in audit_job_detail_schemas():
        if report.ready:
            return report.schema
    for name in list_tenant_schemas():
        if _schema_has_linked_driver(name):
            return name
    names = list_tenant_schemas()
    return names[0] if names else None


def tenant_hint_for_schema(schema: str) -> str:
    """
    Tenant profile UUID for ``X-Tenant-ID``.

    Returns ``''`` when no registry row (Bearer-only JWT tenant binding).
    """
    try:
        from iroad_tenants.models import TenantRegistry

        reg = TenantRegistry.objects.filter(schema_name=schema).first()
        if reg is not None:
            return str(reg.tenant_profile_id)
    except Exception:
        pass
    reg = resolve_active_tenant_registry(schema)
    if reg is not None:
        return str(reg.tenant_profile_id)
    return ''


@dataclass
class JobDetailApiFixtures:
    schema: str
    tenant_hint: str
    driver_a: object
    tenant_user_a: object
    driver_b: object | None
    tenant_user_b: object | None
    own_shipment_id: uuid.UUID | None
    foreign_shipment_id: uuid.UUID | None
    own_movement_id: uuid.UUID | None
    foreign_movement_id: uuid.UUID | None
    other_schema: str | None
    other_tenant_hint: str | None


def load_job_detail_api_fixtures(schema: str) -> JobDetailApiFixtures:
    from django_tenants.utils import schema_context

    from mobile_api.helpers.dashboard_security import (
        movement_queryset_for_driver,
        shipment_queryset_for_driver,
    )
    from tenant_workspace.models import (
        DriverMaster,
        TenantShipment,
        TenantTruckMovementLog,
        TenantUser,
    )

    with schema_context(schema):
        driver_a = None
        tenant_user_a = None
        for candidate in (
            DriverMaster.objects.filter(
                driver_status=DriverMaster.Status.ACTIVE,
                user_account_id__isnull=False,
            )
            .select_related('user_account_id')
            .order_by('pk')[:80]
        ):
            tu = candidate.user_account_id
            if tu is None or tu.is_deleted or tu.status != TenantUser.Status.ACTIVE:
                continue
            driver_a = candidate
            tenant_user_a = tu
            break
        if driver_a is None:
            for tu in TenantUser.objects.filter(
                is_deleted=False,
                status=TenantUser.Status.ACTIVE,
            ).order_by('pk')[:80]:
                candidate = get_driver_master_by_user(tu, schema)
                if candidate is None or candidate.driver_status != DriverMaster.Status.ACTIVE:
                    continue
                driver_a = candidate
                tenant_user_a = tu
                break
        if driver_a is None:
            orphan_driver = DriverMaster.objects.filter(
                driver_status=DriverMaster.Status.ACTIVE,
            ).first()
            orphan_user = TenantUser.objects.filter(
                is_deleted=False,
                status=TenantUser.Status.ACTIVE,
            ).first()
            if orphan_driver is None or orphan_user is None:
                raise RuntimeError(
                    f'No linkable driver/user pair in schema {schema}',
                )
            if orphan_driver.user_account_id_id is None:
                orphan_driver.user_account_id = orphan_user
                orphan_driver.save(update_fields=['user_account_id'])
            driver_a = orphan_driver
            tenant_user_a = orphan_user

        driver_b = None
        tenant_user_b = None
        for tu in TenantUser.objects.filter(
            is_deleted=False,
            status=TenantUser.Status.ACTIVE,
        ).exclude(pk=tenant_user_a.pk).order_by('pk')[:80]:
            candidate = get_driver_master_by_user(tu, schema)
            if candidate is None or candidate.driver_status != DriverMaster.Status.ACTIVE:
                continue
            if candidate.pk == driver_a.pk:
                continue
            driver_b = candidate
            tenant_user_b = tu
            break

        own_ship = (
            shipment_queryset_for_driver(driver_a).order_by('-updated_at').first()
        )
        if own_ship is None:
            own_ship = TenantShipment.objects.create(
                shipment_id=uuid.uuid4(),
                shipment_no=f'JD-API-{uuid.uuid4().hex[:8]}',
                booking_item_ref='JD-API',
                shipment_status=TenantShipment.ShipmentStatus.LOADED,
                sourcing_mode=TenantShipment.SourcingMode.IN_SOURCE,
                driver=driver_a,
            )
        own_shipment_id = own_ship.shipment_id

        foreign_ship = (
            TenantShipment.objects.exclude(pk=own_ship.pk)
            .exclude(driver_id=driver_a.pk)
            .order_by('-updated_at')
            .first()
        )
        if foreign_ship is None and driver_b is not None:
            foreign_ship = TenantShipment.objects.create(
                shipment_id=uuid.uuid4(),
                shipment_no=f'JD-API-F-{uuid.uuid4().hex[:8]}',
                booking_item_ref='JD-API-F',
                shipment_status=TenantShipment.ShipmentStatus.LOADED,
                sourcing_mode=TenantShipment.SourcingMode.IN_SOURCE,
                driver=driver_b,
            )
        if foreign_ship is None:
            other_driver = DriverMaster.objects.create(
                driver_code=f'JDAPIF{uuid.uuid4().hex[:6]}',
                driver_status=DriverMaster.Status.ACTIVE,
                driver_source=DriverMaster.DriverSource.IN_SOURCE,
                driver_type=DriverMaster.DriverType.COMPANY,
            )
            foreign_ship = TenantShipment.objects.create(
                shipment_id=uuid.uuid4(),
                shipment_no=f'JD-API-F-{uuid.uuid4().hex[:8]}',
                booking_item_ref='JD-API-F',
                shipment_status=TenantShipment.ShipmentStatus.LOADED,
                sourcing_mode=TenantShipment.SourcingMode.IN_SOURCE,
                driver=other_driver,
            )
        foreign_shipment_id = foreign_ship.shipment_id if foreign_ship else None

        own_mov = (
            movement_queryset_for_driver(driver_a).order_by('-updated_at').first()
        )
        if own_mov is None:
            own_mov = TenantTruckMovementLog.objects.create(
                movement_id=uuid.uuid4(),
                movement_no=f'JD-API-M-{uuid.uuid4().hex[:8]}',
                movement_source='empty',
                empty_move_reason='Depot',
                status=TenantTruckMovementLog.Status.SCHEDULED,
                driver=driver_a,
            )
        own_movement_id = own_mov.movement_id

        foreign_mov = (
            TenantTruckMovementLog.objects.exclude(pk=own_mov.pk)
            .exclude(driver_id=driver_a.pk)
            .order_by('-updated_at')
            .first()
        )
        if foreign_mov is None and driver_b is not None:
            foreign_mov = TenantTruckMovementLog.objects.create(
                movement_id=uuid.uuid4(),
                movement_no=f'JD-API-MF-{uuid.uuid4().hex[:8]}',
                movement_source='empty',
                empty_move_reason='Depot',
                status=TenantTruckMovementLog.Status.SCHEDULED,
                driver=driver_b,
            )
        if foreign_mov is None:
            other_driver = DriverMaster.objects.create(
                driver_code=f'JDAPIF{uuid.uuid4().hex[:6]}',
                driver_status=DriverMaster.Status.ACTIVE,
                driver_source=DriverMaster.DriverSource.IN_SOURCE,
                driver_type=DriverMaster.DriverType.COMPANY,
            )
            foreign_mov = TenantTruckMovementLog.objects.create(
                movement_id=uuid.uuid4(),
                movement_no=f'JD-API-MF-{uuid.uuid4().hex[:8]}',
                movement_source='empty',
                empty_move_reason='Depot',
                status=TenantTruckMovementLog.Status.SCHEDULED,
                driver=other_driver,
            )
        foreign_movement_id = foreign_mov.movement_id if foreign_mov else None

    other_schema = None
    try:
        from iroad_tenants.models import TenantRegistry

        for reg in TenantRegistry.objects.order_by('schema_name'):
            name = str(reg.schema_name).strip()
            if name and name != schema:
                other_schema = name
                break
    except Exception:
        pass
    if other_schema is None:
        for name in list_tenant_schemas():
            if name != schema:
                other_schema = name
                break

    return JobDetailApiFixtures(
        schema=schema,
        tenant_hint=tenant_hint_for_schema(schema),
        driver_a=driver_a,
        tenant_user_a=tenant_user_a,
        driver_b=driver_b,
        tenant_user_b=tenant_user_b,
        own_shipment_id=own_shipment_id,
        foreign_shipment_id=foreign_shipment_id,
        own_movement_id=own_movement_id,
        foreign_movement_id=foreign_movement_id,
        other_schema=other_schema,
        other_tenant_hint=tenant_hint_for_schema(other_schema)
        if other_schema
        else None,
    )


def issue_driver_access_token(
    *,
    tenant_user,
    driver,
    tenant_schema: str,
    extra_claims: dict | None = None,
) -> str:
    claims = build_token_claims(tenant_schema, tenant_user, driver)
    if extra_claims:
        claims.update(extra_claims)
    return generate_access_token(
        str(tenant_user.user_id),
        tenant_schema,
        extra_claims=claims,
    )


def issue_expired_access_token(
    *,
    tenant_user,
    driver,
    tenant_schema: str,
) -> str:
    claims = build_token_claims(tenant_schema, tenant_user, driver)
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': str(tenant_user.user_id),
        'tenant_schema': tenant_schema,
        'token_type': TOKEN_TYPE_ACCESS,
        'iat': int((now - timedelta(hours=2)).timestamp()),
        'exp': int((now - timedelta(hours=1)).timestamp()),
        **claims,
    }
    payload.update(_registered_claims_iss_aud())
    return jwt.encode(payload, _get_signing_key(), algorithm=ALGORITHM)


def issue_token_wrong_driver_id(
    *,
    tenant_user,
    driver,
    tenant_schema: str,
) -> str:
    claims = build_token_claims(tenant_schema, tenant_user, driver)
    claims['driver_id'] = str(uuid.uuid4())
    return generate_access_token(
        str(tenant_user.user_id),
        tenant_schema,
        extra_claims=claims,
    )


def resolve_non_driver_tenant_user(schema: str):
    """Active tenant user with no ``DriverMaster`` link (dispatcher/admin principal)."""
    from django_tenants.utils import schema_context

    from tenant_workspace.models import DriverMaster, TenantUser

    with schema_context(schema):
        linked_ids = DriverMaster.objects.filter(
            user_account_id__isnull=False,
        ).values_list('user_account_id', flat=True)
        user = (
            TenantUser.objects.filter(
                is_deleted=False,
                status=TenantUser.Status.ACTIVE,
            )
            .exclude(pk__in=linked_ids)
            .order_by('pk')
            .first()
        )
        if user is not None:
            return user
        suffix = uuid.uuid4().hex[:8]
        return TenantUser.objects.create(
            username=f'jdapi_nd_{suffix}',
            full_name='JD API Non-Driver',
            email=f'jdapi_nd_{suffix}@test.local',
            password_hash='test-hash',
            status=TenantUser.Status.ACTIVE,
            role_name='Administrator',
            tenant_ref_no=f'JDAPI-ND-{suffix}',
        )


def issue_non_driver_token(*, tenant_user, tenant_schema: str) -> str:
    """Administrator-style token without ``driver_id`` (fails driver RBAC)."""
    return generate_access_token(
        str(tenant_user.user_id),
        tenant_schema,
        extra_claims={
            'email': tenant_user.email,
            'username': tenant_user.username,
            'full_name': tenant_user.full_name,
            'role_name': 'Administrator',
            'is_admin': True,
        },
    )


def api_auth_headers(
    token: str | None,
    *,
    tenant_hint: str | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    if tenant_hint:
        headers['HTTP_X_TENANT_ID'] = str(tenant_hint)
    return headers


MOBILE_API_PREFIX = '/api/v1/mobile/'


def mobile_api_url(suffix: str) -> str:
    path = suffix.lstrip('/')
    return f'{MOBILE_API_PREFIX}{path}'
