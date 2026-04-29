from django.db import migrations, models
import django.db.models.deletion
import django.core.validators
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0030_standardinvoice_customer_logo_path'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubscriptionFAQ',
            fields=[
                ('faq_id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('question', models.CharField(max_length=255, unique=True)),
                ('answer', models.TextField()),
                ('display_order', models.IntegerField(default=1, validators=[django.core.validators.MinValueValidator(1)])),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='subscription_faqs_created', to='superadmin.adminuser')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='subscription_faqs_updated', to='superadmin.adminuser')),
            ],
            options={
                'db_table': 'subscription_faqs',
                'ordering': ['display_order', 'created_at'],
            },
        ),
    ]
