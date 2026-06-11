import os

from django.db import migrations, models


def backfill_attachment_file_titles(apps, schema_editor):
    TenantClientAttachment = apps.get_model('tenant_workspace', 'TenantClientAttachment')
    for att in TenantClientAttachment.objects.filter(attachment_file_title=''):
        stored = getattr(att.attachment_file, 'name', '') or ''
        if not stored:
            continue
        title = os.path.basename(stored)
        if title:
            TenantClientAttachment.objects.filter(pk=att.pk).update(
                attachment_file_title=title,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0103_rename_shipment_pod_permission_form_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantclientattachment',
            name='attachment_file_title',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.RunPython(backfill_attachment_file_titles, migrations.RunPython.noop),
    ]