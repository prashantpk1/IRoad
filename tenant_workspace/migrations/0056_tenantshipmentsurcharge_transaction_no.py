from django.db import migrations, models


FORM_CODE = 'surcharge-sales-transaction'
FORM_LABEL = 'Surcharge Sales Transaction'
PREFIX = 'SST'


def _int_to_alpha(value):
    n = max(1, int(value or 1))
    chars = []
    while n:
        n -= 1
        chars.append(chr(ord('A') + (n % 26)))
        n //= 26
    return ''.join(reversed(chars))


def _render_auto_number(sequence, config):
    n = int(sequence or 1)
    digits = max(1, int(config.number_of_digits or 4))
    if config.sequence_format == 'alpha':
        rendered = _int_to_alpha(n).rjust(digits, 'A')
    elif config.sequence_format == 'alphanumeric':
        number_digits = max(1, digits - 1)
        rendered = f'{_int_to_alpha(n)}{str(n).zfill(number_digits)}'
    else:
        rendered = str(n).zfill(digits)
    return f'{PREFIX}-{rendered}'


def backfill_surcharge_transaction_numbers(apps, schema_editor):
    TenantShipmentSurcharge = apps.get_model('tenant_workspace', 'TenantShipmentSurcharge')
    AutoNumberConfiguration = apps.get_model('tenant_workspace', 'AutoNumberConfiguration')
    AutoNumberSequence = apps.get_model('tenant_workspace', 'AutoNumberSequence')

    config, _ = AutoNumberConfiguration.objects.get_or_create(
        form_code=FORM_CODE,
        defaults={
            'form_label': FORM_LABEL,
            'number_of_digits': 4,
            'sequence_format': 'numeric',
            'is_unique': True,
        },
    )
    sequence, _ = AutoNumberSequence.objects.get_or_create(
        form_code=FORM_CODE,
        defaults={'next_number': 1},
    )

    next_number = int(sequence.next_number or 1)
    rows = TenantShipmentSurcharge.objects.filter(
        transaction_no__isnull=True,
    ).order_by('created_at', 'line_no', 'surcharge_id')

    for surcharge in rows:
        transaction_no = _render_auto_number(next_number, config)
        while TenantShipmentSurcharge.objects.filter(
            transaction_no=transaction_no,
        ).exclude(pk=surcharge.pk).exists():
            next_number += 1
            transaction_no = _render_auto_number(next_number, config)

        surcharge.transaction_no = transaction_no
        surcharge.transaction_sequence = next_number
        surcharge.save(update_fields=['transaction_no', 'transaction_sequence', 'updated_at'])
        next_number += 1

    if next_number != int(sequence.next_number or 1):
        sequence.next_number = next_number
        sequence.save(update_fields=['next_number', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0055_tenantshipmentsurcharge_attachment_file'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='transaction_no',
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='transaction_sequence',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(
            backfill_surcharge_transaction_numbers,
            migrations.RunPython.noop,
        ),
    ]
