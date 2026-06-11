from django.db import migrations

PERMISSION_FLAGS = (
    'can_view',
    'can_create',
    'can_edit',
    'can_delete',
    'can_post',
    'can_approve',
    'can_export',
    'can_print',
)


def _merge_permission_flags(existing, incoming):
    return {
        flag: getattr(existing, flag, False) or getattr(incoming, flag, False)
        for flag in PERMISSION_FLAGS
    }


def rename_shipment_pod_permission_form_name(apps, schema_editor):
    TenantRolePermission = apps.get_model('tenant_workspace', 'TenantRolePermission')
    legacy_rows = TenantRolePermission.objects.filter(
        module_name='Operations',
        form_name='Shipment POD Analysis',
    )
    for legacy in legacy_rows:
        canonical = TenantRolePermission.objects.filter(
            role_id=legacy.role_id,
            module_name='Operations',
            form_name='Shipment PODs',
        ).first()
        if canonical is None:
            legacy.form_name = 'Shipment PODs'
            legacy.save(update_fields=['form_name', 'updated_at'])
            continue
        merged = _merge_permission_flags(canonical, legacy)
        for flag, value in merged.items():
            setattr(canonical, flag, value)
        canonical.save()
        legacy.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0102_drivermaster_created_by_label'),
    ]

    operations = [
        migrations.RunPython(
            rename_shipment_pod_permission_form_name,
            migrations.RunPython.noop,
        ),
    ]
