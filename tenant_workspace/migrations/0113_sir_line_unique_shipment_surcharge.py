from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0112_tenanttruckmovementlog_places_route_fields'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='salesinvoicereportshipment',
            constraint=models.UniqueConstraint(
                condition=Q(('shipment__isnull', False)),
                fields=('report', 'shipment'),
                name='sir_unique_shipment_per_report_uq',
            ),
        ),
        migrations.AddConstraint(
            model_name='salesinvoicereportsurcharge',
            constraint=models.UniqueConstraint(
                condition=Q(('surcharge__isnull', False)),
                fields=('report', 'surcharge'),
                name='sir_unique_surcharge_per_report_uq',
            ),
        ),
    ]
