from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0002_autonumberconfiguration'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='autonumberconfiguration',
            name='next_number',
        ),
    ]
