from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0029_alter_adminsecuritysettings_session_timeout_minutes'),
    ]

    operations = [
        migrations.AddField(
            model_name='standardinvoice',
            name='customer_logo_path',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]

