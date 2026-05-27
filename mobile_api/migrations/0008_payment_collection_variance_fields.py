from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('mobile_api', '0007_hard_pod_custody_promotion_and_integrity'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentcollectionbundle',
            name='variance_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AddField(
            model_name='paymentcollectionbundle',
            name='variance_type',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
    ]
