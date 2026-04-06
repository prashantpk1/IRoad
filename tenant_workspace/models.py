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
