"""Add attachment_storage_path to POD page lines and migrate legacy map_url file paths."""

from django.db import migrations, models


def migrate_legacy_pod_page_attachment_paths(apps, schema_editor):
    pod_page_model = apps.get_model('tenant_workspace', 'TenantShipmentPodPage')
    for line in pod_page_model.objects.all().iterator():
        raw_map = (line.map_url or '').strip()
        if not raw_map:
            continue
        lowered = raw_map.lower()
        if lowered.startswith(('http://', 'https://')):
            continue
        if not line.attachment_storage_path:
            line.attachment_storage_path = raw_map
        line.map_url = ''
        line.save(update_fields=['attachment_storage_path', 'map_url'])


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0113_sir_line_unique_shipment_surcharge'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantshipmentpodpage',
            name='attachment_storage_path',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.RunPython(
            migrate_legacy_pod_page_attachment_paths,
            migrations.RunPython.noop,
        ),
    ]
