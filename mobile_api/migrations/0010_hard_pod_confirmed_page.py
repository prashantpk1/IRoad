# Hard POD per-page physical custody confirmations

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mobile_api', '0009_remove_hardpodreceipt_bundle_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='HardPODConfirmedPage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tenant_schema', models.CharField(db_index=True, max_length=100)),
                ('shipment_id', models.CharField(db_index=True, max_length=64)),
                ('driver_id', models.CharField(db_index=True, max_length=64)),
                ('document_id', models.CharField(blank=True, default='', max_length=64)),
                ('page_id', models.CharField(blank=True, default='', max_length=64)),
                ('line_no', models.PositiveIntegerField(default=1)),
                ('physical_page_no', models.PositiveIntegerField(default=1)),
                ('label', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'submission',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='confirmed_pages',
                        to='mobile_api.hardpodcustodysubmission',
                    ),
                ),
            ],
            options={
                'db_table': 'mobile_hard_pod_confirmed_page',
                'ordering': ['line_no', 'created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='hardpodconfirmedpage',
            constraint=models.UniqueConstraint(
                fields=('submission', 'document_id', 'line_no'),
                name='hard_pod_confirmed_page_uq',
            ),
        ),
    ]
