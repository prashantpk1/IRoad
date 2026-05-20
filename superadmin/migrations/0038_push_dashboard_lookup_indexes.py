# Indexes for mobile dashboard FCM device/receipt lookups (public schema).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0037_ticket_reply_attachment_upload_to'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='pushdevicetoken',
            index=models.Index(
                fields=['tenant', 'user_domain', 'reference_id', 'is_active'],
                name='comm_push_token_drv_lookup_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='pushnotificationreceipt',
            index=models.Index(
                fields=['tenant', 'user_domain', 'reference_id', '-created_at'],
                name='comm_push_rcpt_drv_lookup_idx',
            ),
        ),
    ]
