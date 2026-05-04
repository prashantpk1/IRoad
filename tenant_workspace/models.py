"""
Tables that exist **only** inside each tenant's Postgres schema.

Control Panel / billing ORM stays in ``public`` (``SHARED_APPS``); this app is
listed in ``TENANT_APPS`` and is migrated per tenant via django-tenants.
"""
import os
import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
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
    national_id = models.CharField(max_length=80, blank=True, default='')
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

    def save(self, *args, **kwargs):
        """Enforce tenant Client Account Settings on every persist (not only HTML forms)."""
        from django.core.exceptions import ValidationError

        from tenant_workspace.client_account_document_rules import (
            collect_client_account_document_rule_errors,
        )

        update_fields = kwargs.get('update_fields')
        doc_keys = {
            'client_type',
            'national_id',
            'commercial_registration_no',
            'tax_registration_no',
        }
        needs_doc_rules = update_fields is None or bool(
            doc_keys.intersection(set(update_fields))
        )
        if needs_doc_rules:
            setting = TenantClientAccountSetting.objects.order_by('-updated_at').first()
            if setting is None:
                setting = TenantClientAccountSetting.objects.create()
            errs = collect_client_account_document_rule_errors(
                client_type=self.client_type,
                national_id=self.national_id,
                commercial_registration_no=self.commercial_registration_no,
                tax_registration_no=self.tax_registration_no,
                require_national_id_individual=bool(setting.require_national_id_individual),
                require_commercial_registration_business=bool(
                    setting.require_commercial_registration_business
                ),
                require_tax_vat_registration_business=bool(
                    setting.require_tax_vat_registration_business
                ),
            )
            if errs:
                raise ValidationError({k: [v] for k, v in errs.items()})
        super().save(*args, **kwargs)


class TenantClientAccountSetting(models.Model):
    """Singleton-style CRM defaults and document rules (one row per tenant schema)."""

    setting_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    require_national_id_individual = models.BooleanField(default=True)
    require_commercial_registration_business = models.BooleanField(default=False)
    require_tax_vat_registration_business = models.BooleanField(default=False)
    default_client_status = models.CharField(
        max_length=12,
        choices=[
            (TenantClientAccount.Status.ACTIVE, TenantClientAccount.Status.ACTIVE),
            (TenantClientAccount.Status.INACTIVE, TenantClientAccount.Status.INACTIVE),
        ],
        default=TenantClientAccount.Status.ACTIVE,
    )
    default_client_type = models.CharField(
        max_length=20,
        choices=[
            (TenantClientAccount.ClientType.INDIVIDUAL, TenantClientAccount.ClientType.INDIVIDUAL),
            (TenantClientAccount.ClientType.BUSINESS, TenantClientAccount.ClientType.BUSINESS),
        ],
        default=TenantClientAccount.ClientType.INDIVIDUAL,
    )
    default_preferred_currency = models.CharField(max_length=10, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_client_account_settings'

    def __str__(self):
        return 'Client account settings'


class TenantClientAttachment(models.Model):
    """Tenant-scoped client attachment documents."""

    class Status(models.TextChoices):
        VALID = 'Valid', 'Valid'
        EXPIRED = 'Expired', 'Expired'
        DOES_NOT_EXPIRE = 'Does Not Expire', 'Does Not Expire'

    attachment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attachment_no = models.CharField(max_length=64, unique=True)
    attachment_sequence = models.PositiveIntegerField(default=0)
    attachment_date = models.DateField(default=timezone.localdate)
    is_expiry_applicable = models.BooleanField(default=False)
    expiry_date = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DOES_NOT_EXPIRE,
    )
    attachment_file = models.FileField(upload_to='tenant/client_attachments/')
    file_notes = models.TextField(blank=True, default='')
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    client_account = models.ForeignKey(
        TenantClientAccount,
        on_delete=models.CASCADE,
        related_name='attachments',
        db_column='client_id',
    )

    class Meta:
        db_table = 'tenant_client_attachments'
        ordering = ['-created_at']

    def __str__(self):
        return self.attachment_no

    @property
    def file_name(self):
        name = getattr(self.attachment_file, 'name', '') or ''
        return os.path.basename(name) if name else ''

    @property
    def computed_status(self):
        """Valid / Expired / Does Not Expire from expiry flags and dates (calendar-aware)."""
        if not self.is_expiry_applicable:
            return self.Status.DOES_NOT_EXPIRE
        if self.expiry_date is None:
            return self.Status.VALID
        if self.expiry_date < timezone.localdate():
            return self.Status.EXPIRED
        return self.Status.VALID

    def save(self, *args, **kwargs):
        self.status = self.computed_status
        super().save(*args, **kwargs)


class TenantClientContact(models.Model):
    """Tenant-scoped client contact person."""

    contact_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    client_account = models.ForeignKey(
        TenantClientAccount,
        on_delete=models.CASCADE,
        related_name='contacts',
        db_column='client_id',
    )

    class Meta:
        db_table = 'tenant_client_contacts'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class TenantClientContract(models.Model):
    """Tenant-scoped single contract per client account."""

    class Status(models.TextChoices):
        UPCOMING = 'Upcoming', 'Upcoming'
        ACTIVE = 'Active', 'Active'
        EXPIRED = 'Expired', 'Expired'

    contract_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract_no = models.CharField(max_length=64, unique=True)
    contract_sequence = models.PositiveIntegerField(default=0)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPCOMING,
    )
    notes = models.TextField(blank=True, default='')
    contract_attachment = models.FileField(upload_to='tenant/client_contracts/')
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    client_account = models.OneToOneField(
        TenantClientAccount,
        on_delete=models.CASCADE,
        related_name='contract',
        db_column='client_id',
    )

    class Meta:
        db_table = 'tenant_client_contracts'
        ordering = ['-created_at']

    def __str__(self):
        return self.contract_no

    @property
    def contract_file_name(self):
        name = getattr(self.contract_attachment, 'name', '') or ''
        return os.path.basename(name) if name else ''

    @property
    def has_contract_file(self):
        return bool(getattr(self.contract_attachment, 'name', None))


class TenantClientContractSetting(models.Model):
    """Singleton-style contract notification settings (one row per tenant schema)."""

    class ExpiredHandling(models.TextChoices):
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
        choices=ExpiredHandling.choices,
        default=ExpiredHandling.DO_NOTHING,
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

    def __str__(self):
        return 'Client contract settings'


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


class TenantCargoCategory(models.Model):
    """Cargo category master (tenant schema). Referenced by TenantCargoMaster."""

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    category_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category_code = models.CharField(max_length=64, unique=True)
    category_sequence = models.PositiveIntegerField(default=0)
    name_english = models.CharField(max_length=200)
    name_arabic = models.CharField(max_length=200, blank=True, default='')
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_cargo_category'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.category_code} — {self.name_english}'

    def clean(self):
        errors = {}
        if not (self.name_english or '').strip():
            errors['name_english'] = [_('English name is required.')]
        if errors:
            raise ValidationError(errors)


class TenantCargoMaster(models.Model):
    """CG-001 Cargo Master — client-scoped cargo catalog (tenant schema)."""

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    objects = models.Manager()

    class ActiveCargoManager(models.Manager):
        """Active cargo with active category (for shipment/waybill selection lists)."""

        def get_queryset(self):
            return (
                super()
                .get_queryset()
                .filter(
                    status=TenantCargoMaster.Status.ACTIVE,
                    cargo_category__status=TenantCargoCategory.Status.ACTIVE,
                    client_account__status=TenantClientAccount.Status.ACTIVE,
                )
            )

    active_objects = ActiveCargoManager()

    cargo_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cargo_code = models.CharField(max_length=64, unique=True)
    cargo_sequence = models.PositiveIntegerField(default=0)
    client_account = models.ForeignKey(
        TenantClientAccount,
        on_delete=models.PROTECT,
        related_name='cargo_items',
    )
    display_name = models.CharField(max_length=200)
    arabic_label = models.CharField(max_length=200, blank=True, default='')
    english_label = models.CharField(max_length=200, blank=True, default='')
    cargo_category = models.ForeignKey(
        TenantCargoCategory,
        on_delete=models.PROTECT,
        related_name='cargo_items',
    )
    client_sku_external_ref = models.CharField(max_length=120, blank=True, default='')
    uom = models.CharField(max_length=64, blank=True, default='')
    weight_per_unit = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    volume_per_unit = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    length = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    width = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    height = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    refrigerated_goods = models.BooleanField(default=False)
    min_temp = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    max_temp = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    dangerous_goods = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_cargo_master'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['client_account', 'status'],
                name='tenant_cargo_client_status_idx',
            ),
        ]

    def __str__(self):
        return f'{self.cargo_code} — {self.display_name}'

    def clean(self):
        errors = {}

        if not (self.display_name or '').strip():
            errors['display_name'] = [_('Display name is required.')]

        if self.refrigerated_goods:
            if self.min_temp is None:
                errors['min_temp'] = [
                    _('Min temperature is required when refrigerated goods is enabled.'),
                ]
            if self.max_temp is None:
                errors['max_temp'] = [
                    _('Max temperature is required when refrigerated goods is enabled.'),
                ]
            if (
                self.min_temp is not None
                and self.max_temp is not None
                and self.min_temp > self.max_temp
            ):
                errors['max_temp'] = [
                    _('Max temperature must be greater than or equal to min temperature.'),
                ]

        for fname in (
            'weight_per_unit',
            'volume_per_unit',
            'length',
            'width',
            'height',
        ):
            val = getattr(self, fname)
            if val is not None and val < 0:
                errors[fname] = [_('Must be zero or greater.')]

        if errors:
            raise ValidationError(errors)


class TenantCargoMasterAttachment(models.Model):
    """Optional file attachments on a cargo master row."""

    attachment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cargo_master = models.ForeignKey(
        TenantCargoMaster,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    file = models.FileField(upload_to='tenant/cargo_master_attachments/')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tenant_cargo_master_attachment'
        ordering = ['created_at']

    def __str__(self):
        return str(self.attachment_id)


class TenantLocationMaster(models.Model):
    """LC-001 Location Master (tenant schema)."""

    class LocationType(models.TextChoices):
        CITY = 'City', 'City'
        AREA = 'Area', 'Area'
        OTHER = 'Other', 'Other'

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    class ActiveServiceableManager(models.Manager):
        """Locations available for new operational use."""

        def get_queryset(self):
            return super().get_queryset().filter(
                status=TenantLocationMaster.Status.ACTIVE,
                is_serviceable=True,
                country__is_active=True,
            )

    objects = models.Manager()
    active_serviceable_objects = ActiveServiceableManager()

    location_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    location_code = models.CharField(max_length=64, unique=True)
    location_sequence = models.PositiveIntegerField(default=0)
    country = models.ForeignKey(
        'superadmin.Country',
        on_delete=models.PROTECT,
        related_name='tenant_locations',
    )
    province = models.CharField(max_length=120, blank=True, default='')
    location_name_arabic = models.CharField(max_length=200, blank=True, default='')
    location_name_english = models.CharField(max_length=200, blank=True, default='')
    display_label = models.CharField(max_length=200)
    location_type = models.CharField(
        max_length=16,
        choices=LocationType.choices,
        default=LocationType.CITY,
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    is_serviceable = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_location_master'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['country', 'province', 'display_label'],
                name='tenant_location_country_province_label_uq',
            ),
        ]

    def __str__(self):
        return f'{self.location_code} — {self.display_label}'

    def clean(self):
        errors = {}
        if not (self.display_label or '').strip():
            errors['display_label'] = [_('Display label is required.')]
        if self.country_id and not getattr(self.country, 'is_active', True):
            errors['country'] = [_('Select an active country.')]
        if self.status == self.Status.INACTIVE and self._state.adding:
            errors['status'] = [_('New locations must be created as Active.')]
        if errors:
            raise ValidationError(errors)


class TenantRouteMaster(models.Model):
    """RT-001 Route Master (tenant schema): two-point bi-directional route master."""

    class RouteType(models.TextChoices):
        DOMESTIC = 'Domestic', 'Domestic'
        INTERNATIONAL = 'International', 'International'
        REGIONAL = 'Regional', 'Regional'
        OTHER = 'Other', 'Other'

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    class EligibleForOperationalManager(models.Manager):
        """Routes selectable for new operational use (active route + eligible endpoints)."""

        def get_queryset(self):
            return (
                super()
                .get_queryset()
                .filter(
                    status=TenantRouteMaster.Status.ACTIVE,
                    origin_point__status=TenantLocationMaster.Status.ACTIVE,
                    destination_point__status=TenantLocationMaster.Status.ACTIVE,
                    origin_point__is_serviceable=True,
                    destination_point__is_serviceable=True,
                    origin_point__country__is_active=True,
                    destination_point__country__is_active=True,
                )
            )

    route_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route_code = models.CharField(max_length=64, unique=True)
    route_sequence = models.PositiveIntegerField(default=0)
    route_label = models.CharField(max_length=200)
    route_type = models.CharField(
        max_length=24,
        choices=RouteType.choices,
        default=RouteType.DOMESTIC,
    )
    origin_point = models.ForeignKey(
        TenantLocationMaster,
        on_delete=models.PROTECT,
        related_name='origin_routes',
        db_column='origin_location_id',
    )
    destination_point = models.ForeignKey(
        TenantLocationMaster,
        on_delete=models.PROTECT,
        related_name='destination_routes',
        db_column='destination_location_id',
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    distance_km = models.DecimalField(max_digits=10, decimal_places=1, default=0)
    estimated_duration_h = models.DecimalField(max_digits=8, decimal_places=1, default=0)
    has_customs = models.BooleanField(default=False)
    has_toll_gates = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()
    eligible_for_operational_use = EligibleForOperationalManager()

    class Meta:
        db_table = 'tenant_route_master'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['route_type', 'origin_point', 'destination_point'],
                name='tenant_route_type_origin_destination_uq',
            ),
        ]

    def __str__(self):
        return f'{self.route_code} — {self.route_label}'

    @staticmethod
    def derive_has_customs(origin, destination):
        """
        PCS RT-001: Has Customs is True when origin and destination are in **different**
        countries (cross-border). Same country → False. Missing country id → False.
        """
        oc = getattr(origin, 'country_id', None)
        dc = getattr(destination, 'country_id', None)
        return bool(oc and dc and oc != dc)

    def clean(self):
        errors = {}
        if self.origin_point_id and self.destination_point_id:
            if self.origin_point_id == self.destination_point_id:
                errors['destination_point'] = [_('Origin and destination must be different.')]
            else:
                o = self.origin_point
                d = self.destination_point
                label = f'{o.display_label} — {d.display_label}'.strip()
                if label:
                    self.route_label = label[: self._meta.get_field('route_label').max_length]

                self.has_customs = TenantRouteMaster.derive_has_customs(o, d)

                dup_qs = TenantRouteMaster.objects.filter(
                    route_type=self.route_type,
                ).filter(
                    Q(origin_point_id=o.location_id, destination_point_id=d.location_id)
                    | Q(origin_point_id=d.location_id, destination_point_id=o.location_id)
                )
                if self.pk:
                    dup_qs = dup_qs.exclude(pk=self.pk)
                if dup_qs.exists():
                    errors['destination_point'] = [
                        _(
                            'A route for this type and location pair already exists '
                            '(including the reverse direction).'
                        )
                    ]
        if self.distance_km is not None and self.distance_km < 0:
            errors['distance_km'] = [_('Distance cannot be negative.')]
        if self.estimated_duration_h is not None and self.estimated_duration_h < 0:
            errors['estimated_duration_h'] = [_('Estimated duration cannot be negative.')]
        if errors:
            raise ValidationError(errors)

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
