from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0022_supportticket_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='addonspricingpolicy',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='adminuser',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='commgateway',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='notificationtemplate',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='paymentgateway',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='promocode',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='subscriptionplan',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='taxcode',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='tenantprofile',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
    ]
