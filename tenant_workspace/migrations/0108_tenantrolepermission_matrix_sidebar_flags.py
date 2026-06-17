from django.db import migrations, models

from iroad_tenants.tenant_permission_matrix import (
    TENANT_PERMISSION_FLAGS,
    TENANT_PERMISSION_LOCATION_ALIASES,
    resolve_canonical_form_name,
)

LEGACY_PERMISSION_FLAGS = (
    'can_view',
    'can_create',
    'can_edit',
    'can_delete',
    'can_post',
    'can_approve',
    'can_export',
    'can_print',
)


def _resolve_location(module_name, form_name):
    canonical_form = resolve_canonical_form_name(form_name)
    return TENANT_PERMISSION_LOCATION_ALIASES.get(
        (module_name, form_name),
        TENANT_PERMISSION_LOCATION_ALIASES.get(
            (module_name, canonical_form),
            (module_name, canonical_form),
        ),
    )


def _legacy_flags(permission):
    return {flag: getattr(permission, flag, False) for flag in LEGACY_PERMISSION_FLAGS}


def _migrate_permission_flags(permission):
    legacy = _legacy_flags(permission)
    any_legacy = any(legacy.values())
    permission.can_access = any_legacy
    permission.can_write = (
        legacy['can_create']
        or legacy['can_edit']
        or legacy['can_delete']
        or legacy['can_post']
    )
    permission.can_read = legacy['can_view']
    permission.can_view = legacy['can_view']
    permission.can_edit = legacy['can_edit']
    permission.can_export = legacy['can_export']
    permission.can_approve = legacy['can_approve'] or legacy['can_post']
    permission.can_print = legacy['can_print']


def _merge_new_flags(existing, incoming):
    return {
        flag: getattr(existing, flag, False) or getattr(incoming, flag, False)
        for flag in TENANT_PERMISSION_FLAGS
    }


def migrate_tenant_permission_matrix(apps, schema_editor):
    TenantRolePermission = apps.get_model('tenant_workspace', 'TenantRolePermission')
    for permission in TenantRolePermission.objects.all().iterator():
        _migrate_permission_flags(permission)
        module_name, form_name = _resolve_location(
            permission.module_name,
            permission.form_name,
        )
        permission.module_name = module_name
        permission.form_name = form_name
        permission.save()

    seen = {}
    duplicates = []
    for permission in TenantRolePermission.objects.all().iterator():
        key = (permission.role_id, permission.module_name, permission.form_name)
        if key in seen:
            duplicates.append((seen[key], permission))
        else:
            seen[key] = permission

    for canonical, legacy in duplicates:
        merged = _merge_new_flags(canonical, legacy)
        for flag, value in merged.items():
            setattr(canonical, flag, value)
        canonical.save()
        legacy.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0107_tenantserviceitemcategory_and_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantrolepermission',
            name='can_access',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='tenantrolepermission',
            name='can_write',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='tenantrolepermission',
            name='can_read',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            migrate_tenant_permission_matrix,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name='tenantrolepermission',
            name='can_create',
        ),
        migrations.RemoveField(
            model_name='tenantrolepermission',
            name='can_delete',
        ),
        migrations.RemoveField(
            model_name='tenantrolepermission',
            name='can_post',
        ),
    ]
