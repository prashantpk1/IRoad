import uuid

from django.db import migrations, models
import django.db.models.deletion


def seed_service_item_categories(apps, schema_editor):
    TenantServiceItemCategory = apps.get_model('tenant_workspace', 'TenantServiceItemCategory')
    TenantServiceItemMaster = apps.get_model('tenant_workspace', 'TenantServiceItemMaster')

    seed_names = [
        'Service Category 1',
        'Service Category 2',
        'Service Category 3',
    ]
    existing_names = set(
        TenantServiceItemMaster.objects.exclude(category_name='').values_list('category_name', flat=True)
    )
    all_names = sorted({name.strip() for name in seed_names + list(existing_names) if (name or '').strip()})

    name_to_category = {}
    sequence = 1
    for name in all_names:
        category = TenantServiceItemCategory.objects.create(
            category_id=uuid.uuid4(),
            category_code=f'SC-{sequence:04d}',
            category_sequence=sequence,
            name_english=name,
            name_arabic='',
            status='Active',
        )
        name_to_category[name] = category
        sequence += 1

    for item in TenantServiceItemMaster.objects.all().iterator():
        category = name_to_category.get((item.category_name or '').strip())
        if category and not item.service_category_id:
            item.service_category_id = category.category_id
            item.save(update_fields=['service_category_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0106_tenantaddressmaster_extension'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantServiceItemCategory',
            fields=[
                ('category_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('category_code', models.CharField(max_length=64, unique=True)),
                ('category_sequence', models.PositiveIntegerField(default=0)),
                ('name_english', models.CharField(max_length=200)),
                ('name_arabic', models.CharField(blank=True, default='', max_length=200)),
                ('status', models.CharField(choices=[('Active', 'Active'), ('Inactive', 'Inactive')], default='Active', max_length=12)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Service Item Category',
                'verbose_name_plural': 'Service Item Categories',
                'db_table': 'tenant_service_item_category',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddField(
            model_name='tenantserviceitemmaster',
            name='service_category',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='service_items',
                to='tenant_workspace.tenantserviceitemcategory',
            ),
        ),
        migrations.RunPython(seed_service_item_categories, migrations.RunPython.noop),
    ]
