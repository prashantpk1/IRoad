"""
Tables that exist **only** inside each tenant's Postgres schema.

Control Panel / billing ORM stays in ``public`` (``SHARED_APPS``); this app is
listed in ``TENANT_APPS`` and is migrated per tenant via django-tenants.
"""
from django.db import models
import uuid


class TenantSchemaVersion(models.Model):
    """
    Lightweight row used to verify tenant-schema routing and migrations.
    Extend this app with operational models (drivers, shipments, etc.).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.PositiveSmallIntegerField(default=1)
    notes = models.CharField(max_length=255, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_schema_version'

    def __str__(self):
        return f'tenant workspace v{self.schema_version}'


class AutoNumberConfiguration(models.Model):
    """Per-tenant auto numbering settings by form code."""

    class SequenceFormat(models.TextChoices):
        NUMERIC = 'numeric', 'Numeric'
        ALPHA = 'alpha', 'Alphabetic'
        ALPHANUMERIC = 'alphanumeric', 'Alphanumeric'

    form_code = models.CharField(max_length=100, unique=True)
    form_label = models.CharField(max_length=150)
    number_of_digits = models.PositiveSmallIntegerField(default=4)
    sequence_format = models.CharField(
        max_length=20,
        choices=SequenceFormat.choices,
        default=SequenceFormat.NUMERIC,
    )
    is_unique = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_auto_number_configuration'

    def __str__(self):
        return f'{self.form_label} ({self.form_code})'
