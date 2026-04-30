from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0031_subscriptionfaq'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriptionplan',
            name='is_admin_only_plan',
            field=models.BooleanField(default=False),
        ),
    ]
