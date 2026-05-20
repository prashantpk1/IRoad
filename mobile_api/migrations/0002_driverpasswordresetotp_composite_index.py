# OTP lookup hot path: tenant_schema + email + status (see get_valid_otp / get_verified_otp).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mobile_api', '0001_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='driverpasswordresetotp',
            index=models.Index(
                fields=['tenant_schema', 'email', 'status'],
                name='ma_otp_tenant_email_status',
            ),
        ),
    ]
