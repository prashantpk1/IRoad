from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0032_subscriptionplan_is_admin_only_plan'),
    ]

    operations = [
        migrations.AddField(
            model_name='planpricingcycle',
            name='is_admin_only_cycle',
            field=models.BooleanField(default=False),
        ),
    ]
