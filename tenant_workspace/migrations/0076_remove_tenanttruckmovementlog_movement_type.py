# Remove movement_type from truck movement log (not used on form).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0075_tenanttruckmovementlog_movement_type'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='tenanttruckmovementlog',
            name='tenant_tml_type_idx',
        ),
        migrations.RemoveField(
            model_name='tenanttruckmovementlog',
            name='movement_type',
        ),
    ]
