# Align migration state with TenantAddressMaster ORM (serialize flag, Country FK options).

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0033_planpricingcycle_is_admin_only_cycle'),
        ('tenant_workspace', '0012_tenantaddressmaster_country_fk'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenantaddressmaster',
            name='address_id',
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, primary_key=True, serialize=False
            ),
        ),
        migrations.AlterField(
            model_name='tenantaddressmaster',
            name='country',
            field=models.ForeignKey(
                db_column='country_id',
                db_constraint=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='+',
                to='superadmin.country',
            ),
        ),
    ]
