"""
Tables that exist **only** inside each tenant's Postgres schema.

Control Panel / billing ORM stays in ``public`` (``SHARED_APPS``); this app is
listed in ``TENANT_APPS`` and is migrated per tenant via django-tenants.
"""
from django.db import models
from django.db import transaction
from django.core.exceptions import ValidationError
import uuid
import os
import re
from django.utils import timezone


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
    national_id = models.CharField(max_length=80, blank=True, default='')
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


class TenantClientAccountSetting(models.Model):
    """Tenant-scoped client account onboarding/settings rules."""

    class DefaultClientStatus(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    class DefaultClientType(models.TextChoices):
        INDIVIDUAL = 'Individual', 'Individual'
        BUSINESS = 'Business', 'Business'

    setting_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    require_national_id_individual = models.BooleanField(default=True)
    require_commercial_registration_business = models.BooleanField(default=False)
    require_tax_vat_registration_business = models.BooleanField(default=False)
    default_client_status = models.CharField(
        max_length=12,
        choices=DefaultClientStatus.choices,
        default=DefaultClientStatus.ACTIVE,
    )
    default_client_type = models.CharField(
        max_length=20,
        choices=DefaultClientType.choices,
        default=DefaultClientType.INDIVIDUAL,
    )
    default_preferred_currency = models.CharField(max_length=10, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_client_account_settings'

    def __str__(self):
        return f'Client Account Settings ({self.setting_id})'


class TenantClientAttachment(models.Model):
    """Tenant-scoped client attachment master (CA-ATT-002)."""

    class Status(models.TextChoices):
        VALID = 'Valid', 'Valid'
        EXPIRED = 'Expired', 'Expired'
        DOES_NOT_EXPIRE = 'Does Not Expire', 'Does Not Expire'

    attachment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attachment_no = models.CharField(max_length=64, unique=True)
    attachment_sequence = models.PositiveIntegerField(default=0)
    client_account = models.ForeignKey(
        TenantClientAccount,
        on_delete=models.CASCADE,
        related_name='attachments',
        db_column='client_id',
    )
    attachment_date = models.DateField(default=timezone.localdate)
    is_expiry_applicable = models.BooleanField(default=False)
    expiry_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DOES_NOT_EXPIRE)
    attachment_file = models.FileField(upload_to='tenant/client_attachments/')
    file_notes = models.TextField(blank=True, default='')
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_client_attachments'
        ordering = ['-created_at']

    def _derived_status(self):
        if not self.is_expiry_applicable:
            return self.Status.DOES_NOT_EXPIRE
        if not self.expiry_date:
            return self.Status.DOES_NOT_EXPIRE
        return self.Status.EXPIRED if self.expiry_date < timezone.localdate() else self.Status.VALID

    def save(self, *args, **kwargs):
        if not self.is_expiry_applicable:
            self.expiry_date = None
        self.status = self._derived_status()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.attachment_no} - {self.client_account.account_no}'

    @property
    def file_name(self):
        return os.path.basename(self.attachment_file.name or '')


class TenantClientContact(models.Model):
    """Tenant-scoped client contacts (CA-CC-003)."""

    contact_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_account = models.ForeignKey(
        TenantClientAccount,
        on_delete=models.CASCADE,
        related_name='contacts',
        db_column='client_id',
    )
    name = models.CharField(max_length=200)
    email = models.EmailField(max_length=150, blank=True, default='')
    mobile_number = models.CharField(max_length=30, blank=True, default='')
    telephone_number = models.CharField(max_length=30, blank=True, default='')
    extension = models.CharField(max_length=30, blank=True, default='')
    position = models.CharField(max_length=120, blank=True, default='')
    is_primary = models.BooleanField(default=False)
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_client_contacts'
        ordering = ['-created_at']

    def clean(self):
        errors = {}
        if self.is_primary and not (self.email or self.mobile_number or self.telephone_number):
            errors['is_primary'] = (
                'Primary contact must have at least one reachable method: Email, Mobile, or Telephone.'
            )

        phone_pattern = re.compile(r'^[0-9+\-\s()]+$')
        if self.mobile_number and not phone_pattern.match(self.mobile_number):
            errors['mobile_number'] = 'Mobile Number should contain only numeric/phone characters.'
        if self.telephone_number and not phone_pattern.match(self.telephone_number):
            errors['telephone_number'] = 'Telephone Number should contain only numeric/phone characters.'
        if self.extension and not re.fullmatch(r'[0-9]+', self.extension):
            errors['extension'] = 'Extension should contain digits only.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.is_primary:
                self.__class__.objects.filter(client_account=self.client_account).exclude(
                    pk=self.pk
                ).update(is_primary=False)

    def __str__(self):
        return f'{self.name} - {self.client_account.account_no}'


class TenantClientContract(models.Model):
    """Tenant-scoped client contract master (CA-CTR-004)."""

    class Status(models.TextChoices):
        UPCOMING = 'Upcoming', 'Upcoming'
        ACTIVE = 'Active', 'Active'
        EXPIRED = 'Expired', 'Expired'

    contract_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract_no = models.CharField(max_length=64, unique=True)
    contract_sequence = models.PositiveIntegerField(default=0)
    client_account = models.OneToOneField(
        TenantClientAccount,
        on_delete=models.CASCADE,
        related_name='contract',
        db_column='client_id',
    )
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPCOMING)
    notes = models.TextField(blank=True, default='')
    contract_attachment = models.FileField(upload_to='tenant/client_contracts/')
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_client_contracts'
        ordering = ['-created_at']

    def clean(self):
        if self.end_date <= self.start_date:
            raise ValidationError('End Date must be greater than Start Date.')

    def _derived_status(self):
        today = timezone.localdate()
        if self.end_date < today:
            return self.Status.EXPIRED
        if self.start_date > today:
            return self.Status.UPCOMING
        return self.Status.ACTIVE

    def save(self, *args, **kwargs):
        self.full_clean()
        self.status = self._derived_status()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.contract_no} - {self.client_account.account_no}'


class TenantClientContractSetting(models.Model):
    """Tenant-level settings controlling expired contract behavior."""

    class ExpiredContractHandlingMode(models.TextChoices):
        AUTO_DEACTIVATE = 'Auto-Deactivate', 'Auto-Deactivate'
        DO_NOTHING = 'Do Nothing', 'Do Nothing'
        DEACTIVATE_AFTER_GRACE = 'Deactivate After Grace', 'Deactivate After Grace'

    class NotificationFrequency(models.TextChoices):
        ONCE = 'Once', 'Once'
        DAILY = 'Daily', 'Daily'
        WEEKLY = 'Weekly', 'Weekly'

    class NotificationAudience(models.TextChoices):
        SYSTEM_ADMIN = 'System Admin', 'System Admin'
        ADMIN_FINANCE = 'Admin+Finance', 'Admin+Finance'

    setting_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    expired_contract_handling_mode = models.CharField(
        max_length=30,
        choices=ExpiredContractHandlingMode.choices,
        default=ExpiredContractHandlingMode.DO_NOTHING,
    )
    grace_period_days = models.PositiveSmallIntegerField(default=30)
    pre_expiry_notification_days = models.PositiveSmallIntegerField(default=30)
    post_expiry_notification_days = models.PositiveSmallIntegerField(default=30)
    notification_frequency = models.CharField(
        max_length=10,
        choices=NotificationFrequency.choices,
        default=NotificationFrequency.DAILY,
    )
    notification_audience = models.CharField(
        max_length=20,
        choices=NotificationAudience.choices,
        default=NotificationAudience.SYSTEM_ADMIN,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_client_contract_settings'

    def clean(self):
        if self.grace_period_days < 0 or self.grace_period_days > 365:
            raise ValidationError('Grace Period Days must be between 0 and 365.')
        if self.pre_expiry_notification_days < 0 or self.pre_expiry_notification_days > 180:
            raise ValidationError('Pre-Expiry Notification Days must be between 0 and 180.')
        if self.post_expiry_notification_days < 0 or self.post_expiry_notification_days > 180:
            raise ValidationError('Post-Expiry Notification Days must be between 0 and 180.')

    def __str__(self):
        return f'Client Contract Settings ({self.setting_id})'


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
