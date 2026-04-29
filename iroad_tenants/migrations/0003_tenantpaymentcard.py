from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0023_soft_delete_flags'),
        ('iroad_tenants', '0002_tenantauthtoken'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantPaymentCard',
            fields=[
                ('card_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('cardholder_name', models.CharField(max_length=120)),
                ('brand', models.CharField(blank=True, default='Card', max_length=30)),
                ('last4', models.CharField(max_length=4)),
                ('expiry_month', models.PositiveSmallIntegerField()),
                ('expiry_year', models.PositiveSmallIntegerField()),
                ('is_default', models.BooleanField(default=False)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payment_cards', to='superadmin.tenantprofile')),
            ],
            options={
                'db_table': 'iroad_tenants_payment_cards',
                'ordering': ['-is_default', '-updated_at'],
            },
        ),
    ]
