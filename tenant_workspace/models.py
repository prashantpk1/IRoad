"""
Tables that exist **only** inside each tenant's Postgres schema.

Control Panel / billing ORM stays in ``public`` (``SHARED_APPS``); this app is
listed in ``TENANT_APPS`` and is migrated per tenant via django-tenants.
"""
import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _


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


class AutoNumberSequence(models.Model):
    """Per-tenant sequence counter per form code."""

    form_code = models.CharField(max_length=100, unique=True)
    next_number = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_auto_number_sequence'

    def __str__(self):
        return f'{self.form_code} -> {self.next_number}'


class OrganizationProfile(models.Model):
    """ACC-ORG-001 single organization profile per tenant schema."""

    DATE_FORMAT_CHOICES = [
        ('DD/MM/YYYY', 'DD/MM/YYYY'),
        ('MM/DD/YYYY', 'MM/DD/YYYY'),
        ('YYYY-MM-DD', 'YYYY-MM-DD'),
    ]
    NUMBER_FORMAT_CHOICES = [
        ('1,234.56', '1,234.56 (Standard)'),
        ('1.234,56', '1.234,56 (EU)'),
    ]
    NEGATIVE_FORMAT_CHOICES = [
        ('-100', '-100'),
        ('(100)', '(100)'),
    ]
    SYSTEM_LANGUAGE_CHOICES = [
        ('ar', 'Arabic'),
        ('en', 'English'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_ref_no = models.CharField(max_length=64, unique=True)
    account_sequence = models.PositiveIntegerField(default=1)
    name_ar = models.CharField(max_length=200, blank=True, default='')
    name_en = models.CharField(max_length=200, blank=True, default='')
    cr_number = models.CharField(max_length=50, blank=True, default='')
    tax_number = models.CharField(max_length=50, blank=True, default='')
    owner_user_id = models.CharField(max_length=64, blank=True, default='')
    logo_file = models.ImageField(
        upload_to='tenant/organization_logos/',
        null=True,
        blank=True,
    )
    country_code = models.CharField(max_length=10, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    district = models.CharField(max_length=100, blank=True, default='')
    street = models.CharField(max_length=150, blank=True, default='')
    building_no = models.CharField(max_length=50, blank=True, default='')
    postal_code = models.CharField(max_length=50, blank=True, default='')
    address_line_1 = models.CharField(max_length=255, blank=True, default='')
    address_line_2 = models.CharField(max_length=255, blank=True, default='')
    primary_email = models.EmailField(max_length=150, blank=True, default='')
    primary_mobile = models.CharField(max_length=30, blank=True, default='')
    website = models.URLField(max_length=255, blank=True, default='')
    base_currency_code = models.CharField(max_length=10, blank=True, default='')
    secondary_currency_code = models.CharField(max_length=10, blank=True, default='')
    support_email = models.EmailField(max_length=150, blank=True, default='')
    support_mobile_1 = models.CharField(max_length=30, blank=True, default='')
    support_mobile_2 = models.CharField(max_length=30, blank=True, default='')
    driver_instructions = models.TextField(blank=True, default='')
    system_language = models.CharField(
        max_length=5,
        choices=SYSTEM_LANGUAGE_CHOICES,
        default='en',
    )
    timezone = models.CharField(max_length=64, default='Asia/Riyadh')
    date_format = models.CharField(
        max_length=20,
        choices=DATE_FORMAT_CHOICES,
        default='DD/MM/YYYY',
    )
    number_format = models.CharField(
        max_length=20,
        choices=NUMBER_FORMAT_CHOICES,
        default='1,234.56',
    )
    negative_format = models.CharField(
        max_length=10,
        choices=NEGATIVE_FORMAT_CHOICES,
        default='-100',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_organization_profile'

    def __str__(self):
        return self.name_en or self.tenant_ref_no


class TenantClientAccount(models.Model):
    """Tenant-scoped CRM client account master."""

    class ClientType(models.TextChoices):
        INDIVIDUAL = 'Individual', 'Individual'
        BUSINESS = 'Business', 'Business'

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    account_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account_no = models.CharField(max_length=64, unique=True)
    account_sequence = models.PositiveIntegerField(default=0)
    client_type = models.CharField(
        max_length=20,
        choices=ClientType.choices,
        default=ClientType.INDIVIDUAL,
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    name_arabic = models.CharField(max_length=200, blank=True, default='')
    name_english = models.CharField(max_length=200)
    display_name = models.CharField(max_length=200)
    preferred_currency = models.CharField(max_length=10, blank=True, default='')
    billing_street_1 = models.CharField(max_length=255)
    billing_street_2 = models.CharField(max_length=255, blank=True, default='')
    billing_city = models.CharField(max_length=100)
    billing_region = models.CharField(max_length=100, blank=True, default='')
    postal_code = models.CharField(max_length=30, blank=True, default='')
    country = models.CharField(max_length=10)
    credit_limit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    limit_currency_code = models.CharField(max_length=10, blank=True, default='SAR')
    payment_term_days = models.PositiveIntegerField(default=0)
    commercial_registration_no = models.CharField(max_length=80, blank=True, default='')
    tax_registration_no = models.CharField(max_length=80, blank=True, default='')
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_client_accounts'
        ordering = ['-created_at']

    def __str__(self):
        return self.display_name or self.name_english or self.account_no


class TenantAddressMaster(models.Model):
    """AD-001 Address Master — shipping addresses per client account (tenant schema).

    Country is stored as a logical FK to ``superadmin.Country`` (PK = ``country_code``).
    ``db_constraint=False`` avoids brittle cross-schema DB constraints under django-tenants;
    Django ORM and forms still enforce FK integrity.

    Operational code MUST use ``tenant_workspace.operational_addresses`` —
    e.g. ``get_active_addresses(client_id)`` and
    ``resolve_active_address_for_client(address_id, client_id)`` — so only
    **Active** rows for the **current client** are shown or accepted.
    The ``active_objects`` manager is Active-only and must always be combined
    with ``client_account_id`` (prefer the operational helpers above).
    """

    class AddressCategory(models.TextChoices):
        PICKUP_ADDRESS = 'Pickup Address', 'Pickup Address'
        DELIVERY_ADDRESS = 'Delivery Address', 'Delivery Address'
        BOTH = 'Both', 'Both'

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    objects = models.Manager()

    class ActiveAddressManager(models.Manager):
        def get_queryset(self):
            return super().get_queryset().filter(
                status=TenantAddressMaster.Status.ACTIVE,
            )

    active_objects = ActiveAddressManager()

    address_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    address_code = models.CharField(max_length=64, unique=True)
    address_sequence = models.PositiveIntegerField(default=0)
    client_account = models.ForeignKey(
        TenantClientAccount,
        on_delete=models.PROTECT,
        related_name='addresses',
    )
    display_name = models.CharField(max_length=200)
    arabic_label = models.CharField(max_length=200, blank=True, default='')
    english_label = models.CharField(max_length=200, blank=True, default='')
    address_category = models.CharField(
        max_length=32,
        choices=AddressCategory.choices,
    )
    default_pickup_address = models.BooleanField(default=False)
    default_delivery_address = models.BooleanField(default=False)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    country = models.ForeignKey(
        'superadmin.Country',
        on_delete=models.PROTECT,
        related_name='+',
        to_field='country_code',
        db_column='country_id',
        db_constraint=False,
    )
    province = models.CharField(max_length=120)
    city = models.CharField(max_length=120)
    district = models.CharField(max_length=120, blank=True, default='')
    street = models.CharField(max_length=200, blank=True, default='')
    building_no = models.CharField(max_length=50, blank=True, default='')
    postal_code = models.CharField(max_length=30, blank=True, default='')
    address_line_1 = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True, default='')
    map_link = models.CharField(max_length=512, blank=True, default='')
    site_instructions = models.TextField(blank=True, default='')
    contact_name = models.CharField(max_length=200, blank=True, default='')
    position = models.CharField(max_length=120, blank=True, default='')
    mobile_no_1 = models.CharField(max_length=30)
    mobile_no_2 = models.CharField(max_length=30, blank=True, default='')
    whatsapp_no = models.CharField(max_length=30, blank=True, default='')
    phone_no = models.CharField(max_length=30, blank=True, default='')
    extension = models.CharField(max_length=20, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_address_master'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['client_account', 'status'],
                name='tenant_addr_client_status_idx',
            ),
        ]

    def __str__(self):
        return f'{self.address_code} — {self.display_name}'

    def _normalize_category_from_defaults(self):
        """PCS: defaults force category toward Both."""
        cat = self.address_category
        if self.default_pickup_address and cat == self.AddressCategory.DELIVERY_ADDRESS:
            self.address_category = self.AddressCategory.BOTH
        if self.default_delivery_address and cat == self.AddressCategory.PICKUP_ADDRESS:
            self.address_category = self.AddressCategory.BOTH

    def clean(self):
        """AD-001 validations for programmatic saves (ModelForm invokes this via ``full_clean``)."""
        self._normalize_category_from_defaults()
        errors = {}

        def add(field: str, message):
            errors.setdefault(field, []).append(message)

        if self.client_account_id is None:
            add('client_account', _('Client account is required.'))

        if not (self.display_name or '').strip():
            add('display_name', _('Display name is required.'))

        cat = getattr(self, 'address_category', None)
        valid_categories = {c for c, _ in self.AddressCategory.choices}
        if not cat or cat not in valid_categories:
            add('address_category', _('Address category is required.'))

        if not (self.address_line_1 or '').strip():
            add('address_line_1', _('Address line 1 is required.'))

        mob = ''.join(ch for ch in (self.mobile_no_1 or '') if ch.isdigit())
        if not mob:
            add('mobile_no_1', _('Mobile number is required (digits only).'))

        if not (self.country_id or '').strip():
            add('country', _('Country is required.'))

        if not (self.province or '').strip():
            add('province', _('Province / region is required.'))

        if not (self.city or '').strip():
            add('city', _('City is required.'))

        if errors:
            raise ValidationError(errors)

    def _enforce_default_uniqueness(self):
        """At most one active default pickup and one active default delivery per client."""
        if self.status != self.Status.ACTIVE:
            return
        from tenant_workspace import operational_addresses as op_addr

        qs_base = op_addr.get_active_addresses(
            self.client_account_id,
            select_related_client=False,
        ).exclude(pk=self.address_id)

        if self.default_pickup_address:
            qs_base.filter(default_pickup_address=True).update(default_pickup_address=False)
        if self.default_delivery_address:
            qs_base.filter(default_delivery_address=True).update(default_delivery_address=False)

    @transaction.atomic
    def save(self, *args, **kwargs):
        self._normalize_category_from_defaults()
        super().save(*args, **kwargs)
        self._enforce_default_uniqueness()


class TenantUser(models.Model):
    """Tenant-scoped internal users (stored per tenant schema)."""

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    user_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_ref_no = models.CharField(max_length=64, unique=True, blank=True, default='')
    account_sequence = models.PositiveIntegerField(default=0)
    username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=200)
    email = models.EmailField(max_length=254, unique=True)
    mobile_country_code = models.CharField(max_length=8, blank=True, default='')
    mobile_no = models.CharField(max_length=30, blank=True, default='')
    password_hash = models.CharField(max_length=255)
    temp_password_expires_at = models.DateTimeField(null=True, blank=True)
    role_name = models.CharField(max_length=100, default='Administrator')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    last_login_at = models.DateTimeField(null=True, blank=True)
    login_attempts = models.PositiveIntegerField(default=0)
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_users'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.full_name} ({self.username})'


class TenantRole(models.Model):
    """Tenant-scoped role master."""

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'
        DRAFT = 'Draft', 'Draft'

    role_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role_name_en = models.CharField(max_length=150, unique=True)
    role_name_ar = models.CharField(max_length=150, unique=True)
    description_en = models.CharField(max_length=255, blank=True, default='')
    description_ar = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_roles'
        ordering = ['-created_at']

    def __str__(self):
        return self.role_name_en


class TenantRolePermission(models.Model):
    """Tenant-scoped role permissions matrix by module/form."""

    permission_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(TenantRole, on_delete=models.CASCADE, related_name='permissions')
    module_name = models.CharField(max_length=100)
    form_name = models.CharField(max_length=120)
    can_view = models.BooleanField(default=False)
    can_create = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_post = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)
    can_export = models.BooleanField(default=False)
    can_print = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_role_permissions'
        unique_together = ('role', 'module_name', 'form_name')
        ordering = ['module_name', 'form_name']

    def __str__(self):
        return f'{self.role.role_name_en} - {self.module_name}/{self.form_name}'
