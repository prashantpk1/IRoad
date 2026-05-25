import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0082_tenantbooking_booking_attachment_upload_to'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantbooking',
            name='sales_invoice_report',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='linked_bookings',
                to='tenant_workspace.salesinvoicereport',
            ),
        ),
        migrations.AddField(
            model_name='tenantbooking',
            name='sales_report_status',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Derived from linked Sales Invoice Report (Pending/Submitted/Invoiced).',
                max_length=30,
            ),
        ),
    ]
