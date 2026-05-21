import uuid

from django.db import migrations, models
import django.db.models.deletion


def forward_fill_pod_action_log_fk(apps, schema_editor):
    pod_page_model = apps.get_model('tenant_workspace', 'TenantShipmentPodPage')
    action_log_model = apps.get_model('tenant_workspace', 'TenantOperationActionLog')
    document_model = apps.get_model('tenant_workspace', 'TenantShipmentDocument')

    for page in pod_page_model.objects.all().iterator():
        ref = (getattr(page, 'action_log_ref', '') or '').strip()
        if not ref:
            continue
        shipment_id = None
        if page.document_id:
            doc = document_model.objects.filter(pk=page.document_id).only('shipment_id').first()
            shipment_id = doc.shipment_id if doc else None
        match = None
        if shipment_id:
            match = action_log_model.objects.filter(log_no=ref, shipment_id=shipment_id).first()
        if match is None:
            match = action_log_model.objects.filter(log_no=ref).first()
        if match is None:
            try:
                parsed_id = uuid.UUID(ref)
            except ValueError:
                parsed_id = None
            if parsed_id is not None:
                match = action_log_model.objects.filter(pk=parsed_id).first()
        if match is not None:
            page.action_log_id = match.log_id
            page.save(update_fields=['action_log_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0086_salesinvoicereport_auto_post'),
    ]

    operations = [
        migrations.RenameField(
            model_name='tenantshipmentpodpage',
            old_name='action_log',
            new_name='action_log_ref',
        ),
        migrations.AddField(
            model_name='tenantshipmentpodpage',
            name='action_log',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='pod_page_lines',
                to='tenant_workspace.tenantoperationactionlog',
            ),
        ),
        migrations.RunPython(forward_fill_pod_action_log_fk, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='tenantshipmentpodpage',
            name='action_log_ref',
        ),
    ]
