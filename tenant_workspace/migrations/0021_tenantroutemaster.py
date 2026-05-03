import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('tenant_workspace', '0020_tenant_location_master'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantRouteMaster',
            fields=[
                (
                    'route_id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('route_code', models.CharField(max_length=64, unique=True)),
                ('route_sequence', models.PositiveIntegerField(default=0)),
                ('route_label', models.CharField(max_length=200)),
                (
                    'route_type',
                    models.CharField(
                        choices=[
                            ('Domestic', 'Domestic'),
                            ('International', 'International'),
                            ('Regional', 'Regional'),
                            ('Other', 'Other'),
                        ],
                        default='Domestic',
                        max_length=24,
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
                        default='Active',
                        max_length=12,
                    ),
                ),
                ('distance_km', models.DecimalField(decimal_places=1, default=0, max_digits=10)),
                (
                    'estimated_duration_h',
                    models.DecimalField(decimal_places=1, default=0, max_digits=8),
                ),
                ('has_customs', models.BooleanField(default=False)),
                ('has_toll_gates', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'destination_point',
                    models.ForeignKey(
                        db_column='destination_location_id',
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='destination_routes',
                        to='tenant_workspace.tenantlocationmaster',
                    ),
                ),
                (
                    'origin_point',
                    models.ForeignKey(
                        db_column='origin_location_id',
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='origin_routes',
                        to='tenant_workspace.tenantlocationmaster',
                    ),
                ),
            ],
            options={
                'db_table': 'tenant_route_master',
                'ordering': ['-created_at'],
                'constraints': [
                    models.UniqueConstraint(
                        fields=('route_type', 'origin_point', 'destination_point'),
                        name='tenant_route_type_origin_destination_uq',
                    )
                ],
            },
        ),
    ]
