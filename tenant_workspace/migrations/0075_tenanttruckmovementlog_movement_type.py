# OP-MOV-001: movement_type (Loaded / Empty) on truck movement log.

from django.db import migrations, models


def backfill_movement_type(apps, schema_editor):
    TenantTruckMovementLog = apps.get_model('tenant_workspace', 'TenantTruckMovementLog')
    loaded = 'Loaded'
    empty = 'Empty'
    for movement in TenantTruckMovementLog.objects.all().iterator():
        if movement.shipment_id:
            movement_type = loaded
        elif (movement.empty_move_reason or '').strip():
            movement_type = empty
        else:
            movement_type = loaded if movement.booking_id else empty
        if movement.movement_type != movement_type:
            TenantTruckMovementLog.objects.filter(pk=movement.pk).update(movement_type=movement_type)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0074_tenantoperationactionlog_created_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='movement_type',
            field=models.CharField(
                choices=[('Loaded', 'Loaded'), ('Empty', 'Empty')],
                default='Empty',
                max_length=16,
            ),
        ),
        migrations.RunPython(backfill_movement_type, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(fields=['movement_type'], name='tenant_tml_type_idx'),
        ),
    ]
