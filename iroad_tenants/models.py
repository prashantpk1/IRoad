"""
django-tenants registry (stored in ``public``).

``TenantRegistry`` mirrors each ``TenantProfile`` and owns ``schema_name``.
"""
from django.db import models
from django.utils import timezone
from django_tenants.models import DomainMixin, TenantMixin
import uuid


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


class TenantAuthToken(models.Model):
    """Invite token for tenant set-password flow."""

    class TokenType(models.TextChoices):
        INVITE = 'invite', 'invite'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_profile = models.ForeignKey(
        'superadmin.TenantProfile',
        on_delete=models.CASCADE,
        related_name='tenant_auth_tokens',
    )
    token = models.CharField(max_length=100, unique=True)
    token_type = models.CharField(
        max_length=20,
        choices=TokenType.choices,
        default=TokenType.INVITE,
    )
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired

    def __str__(self):
        return f"{self.token_type} token for {self.tenant_profile.primary_email}"

    class Meta:
        db_table = 'iroad_tenants_auth_tokens'


class TenantPaymentCard(models.Model):
    """Tenant-managed card metadata for default subscription payments."""

    card_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_profile = models.ForeignKey(
        'superadmin.TenantProfile',
        on_delete=models.CASCADE,
        related_name='payment_cards',
    )
    cardholder_name = models.CharField(max_length=120)
    brand = models.CharField(max_length=30, blank=True, default='Card')
    last4 = models.CharField(max_length=4)
    expiry_month = models.PositiveSmallIntegerField()
    expiry_year = models.PositiveSmallIntegerField()
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            TenantPaymentCard.objects.filter(
                tenant_profile=self.tenant_profile,
                is_active=True,
            ).exclude(pk=self.pk).update(is_default=False)

    def __str__(self):
        return f'{self.tenant_profile.company_name} •••• {self.last4}'

    class Meta:
        db_table = 'iroad_tenants_payment_cards'
        ordering = ['-is_default', '-updated_at']
