# AD-001: Replace country_code string with logical FK to superadmin.Country (column country_id).

from django.db import migrations, models
import django.db.models.deletion


def _verify_country_ids(apps, schema_editor):
    """Ensure every tenant row references an existing Country master row."""
    from django_tenants.utils import schema_context

    TenantAddressMaster = apps.get_model('tenant_workspace', 'TenantAddressMaster')

    with schema_context('public'):
        Country = apps.get_model('superadmin', 'Country')
        valid_upper = {
            str(v).strip().upper()
            for v in Country.objects.values_list('country_code', flat=True)
        }

    # Historical model after migration: FK raw value exposed as country_id
    orphaned = []
    for row in TenantAddressMaster.objects.all().iterator():
        cid = getattr(row, 'country_id', None)
        if not cid:
            orphaned.append(('missing-country', str(row.pk)))
            continue
        if str(cid).strip().upper() not in valid_upper:
            orphaned.append((str(cid), str(row.pk)))

    if orphaned:
        sample = orphaned[:25]
        raise ValueError(
            'TenantAddressMaster migration: orphaned country_id references. '
            f'First samples (code, address_id): {sample}'
        )


def noop_reverse_apps(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0011_tenantaddressmaster'),
        ('superadmin', '0033_planpricingcycle_is_admin_only_cycle'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE tenant_address_master RENAME COLUMN country_code TO country_id;',
                    reverse_sql=(
                        'ALTER TABLE tenant_address_master RENAME COLUMN country_id TO country_code;'
                    ),
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name='tenantaddressmaster',
                    name='country_code',
                ),
                migrations.AddField(
                    model_name='tenantaddressmaster',
                    name='country',
                    field=models.ForeignKey(
                        db_column='country_id',
                        db_constraint=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='+',
                        to='superadmin.country',
                        to_field='country_code',
                    ),
                ),
            ],
        ),
        migrations.RunPython(_verify_country_ids, noop_reverse_apps),
    ]
