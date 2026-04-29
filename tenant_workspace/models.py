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
