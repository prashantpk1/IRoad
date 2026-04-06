"""
django-tenants registry (stored in ``public``).

``TenantRegistry`` mirrors each ``TenantProfile`` and owns ``schema_name``.
"""
from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class TenantRegistry(TenantMixin):
    """
    One row per subscriber; ``schema_name`` is the Postgres schema for
    ``TENANT_APPS`` (e.g. ``tenant_workspace``).
    """

    tenant_profile = models.OneToOneField(
        'superadmin.TenantProfile',
        on_delete=models.CASCADE,
        related_name='schema_registry',
    )

    class Meta:
        db_table = 'iroad_tenants_registry'


class TenantSite(DomainMixin):
    """Synthetic hostname for django-tenants (API uses header routing)."""

    class Meta:
        db_table = 'iroad_tenants_domain'
