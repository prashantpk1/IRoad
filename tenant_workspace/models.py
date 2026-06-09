"""
Tables that exist **only** inside each tenant's Postgres schema.

Control Panel / billing ORM stays in ``public`` (``SHARED_APPS``); this app is
listed in ``TENANT_APPS`` and is migrated per tenant via django-tenants.
"""
import os
import re
import uuid
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Sum
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


def _prefixed_upload_name(folder, prefix, identifier, filename):
    ext = os.path.splitext(filename or '')[1].lower() or '.bin'
    entity_id = str(identifier or '').strip() or str(uuid.uuid4())
    entity_id = entity_id.replace('-', '_')
    return f'{folder}/{prefix}_{entity_id}{ext}'


def _random_prefixed_stored_name(folder, prefix, filename):
    """Store as ``{folder}/{prefix}_{32_hex}.ext`` (unique name per upload)."""
    ext = os.path.splitext(filename or '')[1].lower() or '.bin'
    return f'{folder}/{prefix}_{uuid.uuid4().hex}{ext}'


def organization_logo_upload_to(instance, filename):
    return _prefixed_upload_name(
        'tenant/organization_logos',
        'ORG',
        getattr(instance, 'id', None),
        filename,
    )


def client_attachment_upload_to(instance, filename):
    return _prefixed_upload_name(
        'tenant/client_attachments',
        'CA',
        getattr(instance, 'attachment_id', None),
        filename,
    )


def truck_plate_image_upload_to(instance, filename):
    return _random_prefixed_stored_name('trucks/plates', 'TP', filename)


def truck_registration_image_upload_to(instance, filename):
    return _prefixed_upload_name(
        'trucks/registration',
        'TR',
        getattr(instance, 'truck_id', None),
        filename,
    )


def truck_image_upload_to(instance, filename):
    return _random_prefixed_stored_name('trucks/images', 'TI', filename)


def truck_attachment_upload_to(instance, filename):
    """Store as: TA_<attachment_id>.<ext>."""
    return _prefixed_upload_name(
        'trucks/attachments',
        'TA',
        getattr(instance, 'attachment_id', None),
        filename,
    )


def driver_attachment_upload_to(instance, filename):
    """``drivers/attachments/DA_<attachment_id>.<ext>`` (id segment uses underscores, not hyphens)."""
    return _prefixed_upload_name(
        'drivers/attachments',
        'DA',
        getattr(instance, 'attachment_id', None),
        filename,
    )


def driver_id_upload_to(instance, filename):
    driver_id = getattr(instance, 'driver_id', None)
    if not driver_id:
        driver_id = uuid.uuid4()
        setattr(instance, 'driver_id', driver_id)
    return _prefixed_upload_name(
        'drivers/id',
        'DI',
        driver_id,
        filename,
    )


def driver_passport_upload_to(instance, filename):
    driver_id = getattr(instance, 'driver_id', None)
    if not driver_id:
        driver_id = uuid.uuid4()
        setattr(instance, 'driver_id', driver_id)
    return _prefixed_upload_name(
        'drivers/passport',
        'DP',
        driver_id,
        filename,
    )


def driver_license_upload_to(instance, filename):
    driver_id = getattr(instance, 'driver_id', None)
    if not driver_id:
        driver_id = uuid.uuid4()
        setattr(instance, 'driver_id', driver_id)
    return _prefixed_upload_name(
        'drivers/license',
        'DL',
        driver_id,
        filename,
    )


def driver_card_upload_to(instance, filename):
    driver_id = getattr(instance, 'driver_id', None)
    if not driver_id:
        driver_id = uuid.uuid4()
        setattr(instance, 'driver_id', driver_id)
    return _prefixed_upload_name(
        'drivers/card',
        'DC',
        driver_id,
        filename,
    )


def cargo_master_attachment_upload_to(instance, filename):
    return _prefixed_upload_name(
        'tenant/cargo_master_attachments',
        'CGA',
        getattr(instance, 'attachment_id', None),
        filename,
    )


def surcharge_attachment_upload_to(instance, filename):
    return _random_prefixed_stored_name('surcharges/attachments', 'SST', filename)


def operation_action_media_upload_to(instance, filename):
    """``tenant_operation_action_media/OAM_<32_hex>.ext`` per upload."""
    return _random_prefixed_stored_name('tenant_operation_action_media', 'OAM', filename)


def booking_attachment_upload_to(instance, filename):
    """``booking_attachments/BA_<32_hex>.ext`` per upload."""
    return _random_prefixed_stored_name('booking_attachments', 'BA', filename)


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
        upload_to=organization_logo_upload_to,
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
    attachment_file = models.FileField(upload_to=client_attachment_upload_to)
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
    mobile_country_code = models.CharField(max_length=8, blank=True, default='')
    mobile_number = models.CharField(max_length=30, blank=True, default='')
    telephone_country_code = models.CharField(max_length=8, blank=True, default='')
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


def client_contract_upload_to(instance, filename):
    """
    Store contract attachment as: tenant/client_contracts/CD_<contract_id>.<ext>
    """
    return _prefixed_upload_name(
        'tenant/client_contracts',
        'CD',
        getattr(instance, 'contract_id', None),
        filename,
    )


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
    contract_attachment = models.FileField(upload_to=client_contract_upload_to)
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


class TenantInAppNotification(models.Model):
    """In-app notification row for tenant portal bell (per tenant schema)."""

    class Category(models.TextChoices):
        CONTRACT_PRE_EXPIRY = 'contract_pre_expiry', 'Contract Pre-Expiry'
        CONTRACT_POST_EXPIRY = 'contract_post_expiry', 'Contract Post-Expiry'
        CONTRACT_GRACE = 'contract_grace', 'Contract Grace Period'

    notification_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    recipient_key = models.CharField(
        max_length=64,
        db_index=True,
        help_text="'owner' for tenant-owner session, else TenantUser UUID.",
    )
    recipient_user = models.ForeignKey(
        'TenantUser',
        on_delete=models.CASCADE,
        related_name='in_app_notifications',
        null=True,
        blank=True,
    )
    category = models.CharField(max_length=32, choices=Category.choices)
    title = models.CharField(max_length=255)
    message = models.TextField()
    href = models.CharField(max_length=500, blank=True, default='')
    contract = models.ForeignKey(
        TenantClientContract,
        on_delete=models.CASCADE,
        related_name='in_app_notifications',
        null=True,
        blank=True,
    )
    source_key = models.CharField(max_length=128)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_in_app_notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['recipient_key', 'is_read'],
                name='tenant_notif_rcpt_read_idx',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['recipient_key', 'source_key'],
                name='tenant_notif_rcpt_source_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.recipient_key} · {self.title}'


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


class TruckTypeMaster(models.Model):
    """TRT-001 Truck Type Master (tenant schema).

    ``truck_type_code`` is allocated by AutoNumber (prefix TRT) at creation — never user-editable.
    Use ``TruckTypeMaster.active_objects`` in Truck Master dropdowns so only **Active**
    rows are selectable. Rows are deactivated via ``status``, not deleted.
    """

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    objects = models.Manager()

    class ActiveTruckTypeManager(models.Manager):
        def get_queryset(self):
            return super().get_queryset().filter(
                status=TruckTypeMaster.Status.ACTIVE,
            )

    active_objects = ActiveTruckTypeManager()

    truck_type_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    truck_type_code = models.CharField(max_length=64, unique=True)
    truck_type_sequence = models.PositiveIntegerField(default=0)
    english_label = models.CharField(max_length=200)
    arabic_label = models.CharField(max_length=200)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_truck_type_master'
        ordering = ['english_label']
        verbose_name = _('Truck Type')
        verbose_name_plural = _('Truck Types')

    def __str__(self):
        return f'{self.truck_type_code} — {self.english_label}'

    def clean(self):
        """TRT-001 validations for programmatic saves (ModelForm invokes this via ``full_clean``)."""
        errors = {}

        def add(field: str, message):
            errors.setdefault(field, []).append(message)

        if not (self.english_label or '').strip():
            add('english_label', _('English label is required.'))

        if not (self.arabic_label or '').strip():
            add('arabic_label', _('Arabic label is required.'))

        if errors:
            raise ValidationError(errors)


class TruckMaster(models.Model):
    """TR-001 Truck Master (tenant schema).

    ``truck_code`` is allocated by AutoNumber (prefix TR) at creation.
    Cross-schema ``Country`` uses ``db_constraint=False`` (same pattern as ``TenantAddressMaster``).
    """

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    class SourcingMode(models.TextChoices):
        IN_SOURCE = 'In-Source', 'In-Source'
        OUT_SOURCE = 'Out-Source', 'Out-Source'

    objects = models.Manager()

    class ActiveTruckManager(models.Manager):
        def get_queryset(self):
            return super().get_queryset().filter(
                status=TruckMaster.Status.ACTIVE,
            )

    active_objects = ActiveTruckManager()

    truck_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    truck_code = models.CharField(max_length=64, unique=True)
    truck_sequence = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    sourcing_mode = models.CharField(
        max_length=20,
        choices=SourcingMode.choices,
    )
    registration_country = models.ForeignKey(
        'superadmin.Country',
        on_delete=models.PROTECT,
        related_name='+',
        to_field='country_code',
        db_column='registration_country_id',
        db_constraint=False,
    )
    # TODO: Replace with FK to VendorAccount when that module is built
    vendor_account_id = models.CharField(max_length=64, blank=True, default='')
    is_vendor_same_as_owner = models.BooleanField(
        default=False,
        verbose_name=_('Is Company info as same Owner Info'),
    )
    owner_id = models.CharField(max_length=100, blank=True, default='')
    owner_name = models.CharField(max_length=200, blank=True, default='')

    class OperationalStatus(models.TextChoices):
        AVAILABLE = 'Available', _('Available')
        LOADED = 'Loaded', _('Loaded')
        SUSPENDED = 'Suspended', _('Suspended')

    operational_status = models.CharField(
        max_length=20,
        choices=OperationalStatus.choices,
        blank=True,
        default='',
        verbose_name=_('Operational status'),
    )

    plate_number = models.CharField(max_length=100)
    saudi_plate_number = models.CharField(max_length=50, blank=True, default='')
    saudi_english_letters = models.CharField(max_length=10, blank=True, default='')
    saudi_arabic_letters = models.CharField(max_length=10, blank=True, default='')
    non_saudi_plate_number = models.CharField(max_length=100, blank=True, default='')
    plate_image = models.ImageField(upload_to=truck_plate_image_upload_to, blank=True, null=True)

    truck_type = models.ForeignKey(
        TruckTypeMaster,
        on_delete=models.PROTECT,
        related_name='trucks',
    )
    chassis_number_vin = models.CharField(max_length=100, blank=True, default='')
    serial_number = models.CharField(max_length=100, blank=True, default='')
    color = models.CharField(max_length=50, blank=True, default='')
    vehicle_registration_image = models.ImageField(
        upload_to=truck_registration_image_upload_to,
        blank=True,
        null=True,
    )

    axle_count = models.PositiveIntegerField(blank=True, null=True)
    tires_count = models.PositiveIntegerField(blank=True, null=True)
    tare_weight_ton = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    payload_capacity_ton = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    gross_weight_ton = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    volume_m3 = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)

    # TR-001: Link truck to its default driver (optional).
    # Historical note: earlier implementation stored `driver_code` in a CharField.
    default_driver_id = models.ForeignKey(
        'tenant_workspace.DriverMaster',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='trucks_as_default_driver',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_truck_master'
        ordering = ['-created_at']
        verbose_name = _('Truck')
        verbose_name_plural = _('Trucks')
        indexes = [
            models.Index(fields=['truck_code', 'status'], name='tenant_truck_code_status_idx'),
            models.Index(
                fields=['registration_country', 'plate_number'],
                name='tenant_truck_reg_plate_idx',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['registration_country', 'plate_number'],
                name='tenant_truck_regcountry_plate_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.truck_code} — {self.plate_number}'

    def clean(self):
        """TR-001 validations."""
        errors = {}

        def add(field: str, message):
            errors.setdefault(field, []).append(message)

        if self.is_vendor_same_as_owner:
            self.vendor_account_id = (self.owner_id or '').strip()

        if self.sourcing_mode == self.SourcingMode.OUT_SOURCE:
            if not (self.vendor_account_id or '').strip():
                add(
                    'vendor_account_id',
                    _('Vendor is required for Out-Source trucks'),
                )

        country_code = (self.registration_country_id or '').strip().upper()
        plate = (self.plate_number or '').strip()
        saudi_plate = (self.saudi_plate_number or '').strip()
        non_saudi_plate = (self.non_saudi_plate_number or '').strip()

        if country_code == 'SA':
            if not plate:
                add('plate_number', _('Plate number is required for Saudi-registered trucks.'))
            if not saudi_plate:
                add('saudi_plate_number', _('Saudi plate number is required for Saudi Arabia.'))
            english_letters = (self.saudi_english_letters or '').strip()
            if not english_letters:
                add(
                    'saudi_english_letters',
                    _('Saudi English letters are required for Saudi-registered trucks.'),
                )
            arabic_letters = (self.saudi_arabic_letters or '').strip()
            if not arabic_letters:
                add(
                    'saudi_arabic_letters',
                    _('Saudi Arabic letters are required for Saudi-registered trucks.'),
                )
        elif country_code:
            if not non_saudi_plate:
                add(
                    'non_saudi_plate_number',
                    _('Non-Saudi plate number is required when registration country is not Saudi Arabia.'),
                )

        chassis = (self.chassis_number_vin or '').strip()
        if chassis:
            qs = TruckMaster.objects.filter(chassis_number_vin__iexact=chassis)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                add('chassis_number_vin', _('This chassis / VIN is already assigned to another truck.'))

        if self.registration_country_id and plate:
            qs = TruckMaster.objects.filter(
                registration_country_id=self.registration_country_id,
                plate_number=plate,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                add(
                    'plate_number',
                    _('A truck with this plate number already exists for the selected registration country.'),
                )

        payload = self.payload_capacity_ton
        gross = self.gross_weight_ton
        if payload is not None and gross is not None and payload > gross:
            add(
                'payload_capacity_ton',
                _('Payload capacity cannot exceed gross weight'),
            )

        def check_non_negative_decimal(name, value):
            if value is not None and value < 0:
                add(name, _('Must be zero or greater.'))

        check_non_negative_decimal('tare_weight_ton', self.tare_weight_ton)
        check_non_negative_decimal('payload_capacity_ton', self.payload_capacity_ton)
        check_non_negative_decimal('gross_weight_ton', self.gross_weight_ton)
        check_non_negative_decimal('volume_m3', self.volume_m3)

        if self.axle_count is not None and self.axle_count < 0:
            add('axle_count', _('Must be zero or greater.'))
        if self.tires_count is not None and self.tires_count < 0:
            add('tires_count', _('Must be zero or greater.'))

        if errors:
            raise ValidationError(errors)


class TruckDriverAssignmentHistory(models.Model):
    """History of driver assignments per truck (current + ended rows)."""

    assignment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    truck = models.ForeignKey(
        TruckMaster,
        on_delete=models.CASCADE,
        related_name='driver_assignments',
    )
    driver = models.ForeignKey(
        'tenant_workspace.DriverMaster',
        on_delete=models.PROTECT,
        related_name='truck_assignment_history',
    )
    assigned_from = models.DateTimeField(default=timezone.now)
    assigned_to = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_truck_driver_assignment_history'
        ordering = ['-assigned_from', '-created_at']
        indexes = [
            models.Index(fields=['truck', 'assigned_to'], name='truck_drv_assign_cur_idx'),
            models.Index(fields=['driver', 'assigned_from'], name='drv_assign_hist_idx'),
        ]
        verbose_name = _('Truck Driver Assignment History')
        verbose_name_plural = _('Truck Driver Assignment History')

    def __str__(self):
        return f'{self.truck.truck_code} -> {self.driver.driver_code}'

    @property
    def assignment_status(self):
        return 'Current' if self.assigned_to is None else 'Ended'


class TruckImage(models.Model):
    """
    TR-001 truck_images — Multiple image uploads per truck (stored as related rows).

    Spec field ``truck_images`` is modeled as FK rows with ``related_name='truck_images'``.
    """

    image_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    truck = models.ForeignKey(
        TruckMaster,
        on_delete=models.CASCADE,
        related_name='truck_images',
    )
    image = models.ImageField(upload_to=truck_image_upload_to, max_length=500)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tenant_truck_images'
        ordering = ['uploaded_at']
        verbose_name = _('Truck Image')
        verbose_name_plural = _('Truck Images')

    def __str__(self):
        return f'Image for {self.truck.truck_code}'


class TruckAttachment(models.Model):
    """TR-ATT-001 Truck attachment (tenant schema).

    ``status`` (property) is derived from ``is_expiry_applicable`` and ``expiry_date`` only.
    ``record_status`` is the user-editable lifecycle status (Active / Inactive / Pending).
    """

    class Status(models.TextChoices):
        VALID = 'Valid', 'Valid'
        EXPIRED = 'Expired', 'Expired'
        DOES_NOT_EXPIRE = 'Does Not Expire', 'Does Not Expire'

    class RecordStatus(models.TextChoices):
        ACTIVE = 'Active', _('Active')
        INACTIVE = 'Inactive', _('Inactive')
        PENDING = 'Pending', _('Pending')

    _ALLOWED_ATTACHMENT_EXTENSIONS = frozenset(
        {'.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx'},
    )
    ATTACHMENT_MAX_SIZE_MB = 10
    ATTACHMENT_MAX_SIZE_BYTES = ATTACHMENT_MAX_SIZE_MB * 1024 * 1024

    attachment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attachment_no = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        null=True,
        help_text=_('Auto-generated attachment number'),
    )
    attachment_sequence = models.PositiveIntegerField(default=0)
    truck = models.ForeignKey(
        TruckMaster,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    arabic_label = models.CharField(max_length=200, blank=True, default='')
    english_label = models.CharField(max_length=200, blank=True, default='')
    doc_ref_number = models.CharField(max_length=120, blank=True, default='')
    attachment_date = models.DateField(default=date.today)
    is_expiry_applicable = models.BooleanField(default=False)
    expiry_date = models.DateField(blank=True, null=True)
    record_status = models.CharField(
        max_length=20,
        choices=RecordStatus.choices,
        default=RecordStatus.ACTIVE,
        verbose_name=_('Status'),
        help_text=_('Current status of the attachment'),
    )
    stats = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DOES_NOT_EXPIRE,
        editable=False,
        help_text=_('Derived expiry status persisted for reporting.'),
    )
    attachment_file = models.FileField(upload_to=truck_attachment_upload_to, max_length=500)
    file_notes = models.TextField(
        help_text=_('Notes about this attachment document'),
    )
    is_deleted = models.BooleanField(default=False)
    is_deleted_by = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_truck_attachments'
        ordering = ['-attachment_date', '-created_at']
        verbose_name = _('Truck Attachment')
        verbose_name_plural = _('Truck Attachments')

    def __str__(self):
        ref = self.attachment_no or str(self.attachment_id)
        return f'{ref} — {self.truck.truck_code}'

    @property
    def status(self) -> str:
        if not self.is_expiry_applicable:
            return self.Status.DOES_NOT_EXPIRE
        today = timezone.localdate()
        if self.expiry_date is not None and self.expiry_date < today:
            return self.Status.EXPIRED
        return self.Status.VALID

    def save(self, *args, **kwargs):
        self.stats = self.status
        super().save(*args, **kwargs)

    def clean(self):
        errors = {}

        def add(field: str, message):
            errors.setdefault(field, []).append(message)

        if self.is_expiry_applicable:
            if self.expiry_date is None:
                add(
                    'expiry_date',
                    _('Expiry date is required when expiry is applicable'),
                )
        else:
            if self.expiry_date is not None:
                add(
                    'expiry_date',
                    _('Expiry date must be empty when expiry is not applicable'),
                )

        file_name = getattr(self.attachment_file, 'name', None) or ''
        if not file_name.strip():
            add('attachment_file', _('Attachment file is required.'))
        else:
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in self._ALLOWED_ATTACHMENT_EXTENSIONS:
                add(
                    'attachment_file',
                    _(
                        'Allowed file types are PDF, JPG, JPEG, PNG, DOC, DOCX.'
                    ),
                )
            if self.attachment_file:
                try:
                    if self.attachment_file.size > self.ATTACHMENT_MAX_SIZE_BYTES:
                        size_mb = round(self.attachment_file.size / 1024 / 1024, 1)
                        add(
                            'attachment_file',
                            _(
                                f'File size cannot exceed {self.ATTACHMENT_MAX_SIZE_MB}MB. '
                                f'Your file is {size_mb}MB.'
                            ),
                        )
                except AttributeError:
                    pass

        if not (self.file_notes or '').strip():
            add('file_notes', _('File notes are required.'))

        if errors:
            raise ValidationError(errors)


class TruckSettings(models.Model):
    """Singleton truck settings per tenant schema."""

    class DefaultStatus(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        IN_MAINTENANCE = 'In Maintenance', 'In Maintenance'
        INACTIVE = 'Inactive', 'Inactive'

    settings_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    default_truck_status = models.CharField(
        max_length=20,
        choices=DefaultStatus.choices,
        default=DefaultStatus.ACTIVE,
    )
    maintenance_reminder_days = models.PositiveIntegerField(default=30)
    insurance_expiry_alert_days = models.PositiveIntegerField(default=30)
    registration_expiry_alert_days = models.PositiveIntegerField(default=30)
    fuel_consumption_tracking_enabled = models.BooleanField(default=True)
    driver_assignment_required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_truck_settings'
        verbose_name = 'Truck Settings'
        verbose_name_plural = 'Truck Settings'

    def __str__(self):
        return 'Truck Settings'

    @classmethod
    def get_or_create_singleton(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj

    def clean(self):
        errors = {}
        if self.maintenance_reminder_days is not None and not (
            0 <= self.maintenance_reminder_days <= 365
        ):
            errors['maintenance_reminder_days'] = 'Must be between 0 and 365.'
        if self.insurance_expiry_alert_days is not None and not (
            0 <= self.insurance_expiry_alert_days <= 180
        ):
            errors['insurance_expiry_alert_days'] = 'Must be between 0 and 180.'
        if self.registration_expiry_alert_days is not None and not (
            0 <= self.registration_expiry_alert_days <= 180
        ):
            errors['registration_expiry_alert_days'] = 'Must be between 0 and 180.'
        if errors:
            raise ValidationError(errors)


class DriverMaster(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    class DriverSource(models.TextChoices):
        IN_SOURCE = 'In-Source', 'In-Source'
        OUT_SOURCE = 'Out-Source', 'Out-Source'

    class DriverType(models.TextChoices):
        COMPANY = 'Company', 'Company'
        VENDOR = 'Vendor', 'Vendor'
        OTHER = 'Other', 'Other'

    class DocumentStatus(models.TextChoices):
        VALID = 'Valid', 'Valid'
        EXPIRED = 'Expired', 'Expired'
        NOT_PROVIDED = 'Not Provided', 'Not Provided'

    objects = models.Manager()

    class ActiveDriverManager(models.Manager):
        def get_queryset(self):
            return super().get_queryset().filter(
                driver_status=DriverMaster.Status.ACTIVE
            )

    active_objects = ActiveDriverManager()

    # ── Identity ──────────────────────────────────────
    driver_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    driver_code = models.CharField(
        max_length=64,
        unique=True,
    )
    driver_sequence = models.PositiveIntegerField(default=0)

    # ── Section A: Basic Information ──────────────────
    user_account_id = models.OneToOneField(
        'tenant_workspace.TenantUser',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        unique=True,
        related_name='linked_driver_profile',
        db_column='user_account_id',
    )
    driver_source = models.CharField(
        max_length=20,
        choices=DriverSource.choices,
        default=DriverSource.IN_SOURCE,
    )
    vendor_account_id = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='TODO: Replace with FK to VendorAccount',
    )
    driver_status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    driver_type = models.CharField(
        max_length=20,
        choices=DriverType.choices,
        blank=True,
        default='',
    )

    # ── Section B: Driver Information ─────────────────
    arabic_name = models.CharField(max_length=200)
    english_name = models.CharField(
        max_length=200,
        blank=True,
        default='',
    )
    nationality_country = models.ForeignKey(
        'superadmin.Country',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        to_field='country_code',
        db_column='nationality_country_id',
        db_constraint=False,
    )
    birth_date = models.DateField(null=True, blank=True)

    # ── Section C: ID / IQAMA ─────────────────────────
    id_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
    )
    id_expiry_date = models.DateField(null=True, blank=True)
    id_image = models.FileField(
        upload_to=driver_id_upload_to,
        blank=True,
        null=True,
        max_length=500,
    )

    # ── Section D: Passport ───────────────────────────
    passport_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
    )
    passport_expiry_date = models.DateField(null=True, blank=True)
    passport_image = models.FileField(
        upload_to=driver_passport_upload_to,
        blank=True,
        null=True,
        max_length=500,
    )

    # ── Section E: Driving License ────────────────────
    dl_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
    )
    dl_expiry_date = models.DateField(null=True, blank=True)
    dl_image = models.FileField(
        upload_to=driver_license_upload_to,
        blank=True,
        null=True,
        max_length=500,
    )

    # ── Section F: Driver Card ────────────────────────
    card_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
    )
    card_expiry_date = models.DateField(null=True, blank=True)
    card_image = models.FileField(
        upload_to=driver_card_upload_to,
        blank=True,
        null=True,
        max_length=500,
    )

    # ── Section G: Contact ────────────────────────────
    mobile_number = models.CharField(max_length=30)
    whatsapp_number = models.CharField(
        max_length=30,
        blank=True,
        default='',
    )
    whatsapp_same_as_mobile = models.BooleanField(default=False)

    # ── Audit ─────────────────────────────────────────
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_driver_master'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['driver_status'],
                name='tenant_driver_status_idx',
            ),
            models.Index(
                fields=['driver_code'],
                name='tenant_driver_code_idx',
            ),
        ]
        verbose_name = 'Driver'
        verbose_name_plural = 'Drivers'

    def __str__(self):
        return f'{self.driver_code} — {self.arabic_name}'

    # ── Derived document status properties ────────────
    @staticmethod
    def _derive_doc_status(number, expiry_date):
        if not number or not number.strip():
            return DriverMaster.DocumentStatus.NOT_PROVIDED
        today = timezone.localdate()
        if expiry_date and expiry_date < today:
            return DriverMaster.DocumentStatus.EXPIRED
        return DriverMaster.DocumentStatus.VALID

    @property
    def id_status(self):
        return self._derive_doc_status(
            self.id_number, self.id_expiry_date
        )

    @property
    def passport_status(self):
        return self._derive_doc_status(
            self.passport_number, self.passport_expiry_date
        )

    @property
    def dl_status(self):
        return self._derive_doc_status(
            self.dl_number, self.dl_expiry_date
        )

    @property
    def card_status(self):
        return self._derive_doc_status(
            self.card_number, self.card_expiry_date
        )

    # ── Validation ────────────────────────────────────
    def clean(self):
        errors = {}
        today = timezone.localdate()

        # Rule 1: Out-Source requires vendor
        if self.user_account_id_id is None:
            errors['user_account_id'] = 'User account is required'

        if self.driver_source == self.DriverSource.OUT_SOURCE:
            if not self.vendor_account_id or \
               not self.vendor_account_id.strip():
                errors['vendor_account_id'] = (
                    'Vendor account is required '
                    'for Out-Source drivers'
                )

        # Rule 2: arabic_name required
        if not self.arabic_name or not self.arabic_name.strip():
            errors['arabic_name'] = 'Arabic name is required'

        # Rule 3: mobile_number digits only
        if self.mobile_number:
            if not re.match(r'^\d+$', self.mobile_number):
                errors['mobile_number'] = (
                    'Mobile number must contain digits only'
                )

        # Rule 4: whatsapp_number digits only if provided
        if self.whatsapp_number:
            if not re.match(r'^\d+$', self.whatsapp_number):
                errors['whatsapp_number'] = (
                    'WhatsApp number must contain digits only'
                )

        # Rule 5: id_number digits only if provided
        if self.id_number:
            if not re.match(r'^\d+$', self.id_number):
                errors['id_number'] = (
                    'ID number must contain digits only'
                )

        # Rule 6: Uniqueness checks (if provided)
        def _check_unique(field_name, value, label):
            if not value or not value.strip():
                return
            qs = DriverMaster.objects.filter(
                **{field_name: value}
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                errors[field_name] = (
                    f'{label} already exists '
                    f'for another driver'
                )

        _check_unique('id_number', self.id_number, 'ID number')
        _check_unique(
            'passport_number',
            self.passport_number,
            'Passport number',
        )
        _check_unique('dl_number', self.dl_number, 'DL number')
        _check_unique(
            'card_number', self.card_number, 'Card number'
        )

        # Rule 7: Expiry date >= today on CREATE
        def _check_expiry(number, expiry, expiry_field, label):
            if not number or not number.strip():
                return
            if not expiry:
                return
            if not self.pk and expiry < today:
                errors[expiry_field] = (
                    f'{label} expiry date cannot '
                    f'be in the past'
                )

        _check_expiry(
            self.id_number,
            self.id_expiry_date,
            'id_expiry_date',
            'ID',
        )
        _check_expiry(
            self.passport_number,
            self.passport_expiry_date,
            'passport_expiry_date',
            'Passport',
        )
        _check_expiry(
            self.dl_number,
            self.dl_expiry_date,
            'dl_expiry_date',
            'Driving license',
        )
        _check_expiry(
            self.card_number,
            self.card_expiry_date,
            'card_expiry_date',
            'Driver card',
        )

        # Rule 8: whatsapp_same_as_mobile → copy number
        if self.whatsapp_same_as_mobile:
            self.whatsapp_number = self.mobile_number

        if errors:
            raise ValidationError(errors)


class DriverAttachment(models.Model):
    """Driver document attachment.

    ``status`` (property) reflects expiry only. ``record_status`` is the
    user-editable lifecycle status (Active / Inactive / Pending).
    """

    class Status(models.TextChoices):
        VALID = 'Valid', 'Valid'
        EXPIRED = 'Expired', 'Expired'
        DOES_NOT_EXPIRE = 'Does Not Expire', 'Does Not Expire'

    class RecordStatus(models.TextChoices):
        ACTIVE = 'Active', _('Active')
        INACTIVE = 'Inactive', _('Inactive')
        PENDING = 'Pending', _('Pending')

    _ALLOWED_EXTENSIONS = {
        '.pdf', '.jpg', '.jpeg',
        '.png', '.doc', '.docx',
    }
    ATTACHMENT_MAX_SIZE_MB = 10
    ATTACHMENT_MAX_SIZE_BYTES = (
        ATTACHMENT_MAX_SIZE_MB * 1024 * 1024
    )

    attachment_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    attachment_no = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        null=True,
        help_text='Auto-generated attachment number',
    )
    attachment_sequence = models.PositiveIntegerField(default=0)
    driver = models.ForeignKey(
        DriverMaster,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    arabic_label = models.CharField(max_length=200, blank=True, default='')
    english_label = models.CharField(max_length=200, blank=True, default='')
    doc_ref_number = models.CharField(max_length=120, blank=True, default='')
    attachment_date = models.DateField(default=date.today)
    is_expiry_applicable = models.BooleanField(default=False)
    expiry_date = models.DateField(null=True, blank=True)
    record_status = models.CharField(
        max_length=20,
        choices=RecordStatus.choices,
        default=RecordStatus.ACTIVE,
        verbose_name=_('Status'),
        help_text=_('Current status of the attachment'),
    )
    attachment_file = models.FileField(
        upload_to=driver_attachment_upload_to,
        max_length=500,
    )
    file_notes = models.TextField(
        help_text='Describe this document'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_driver_attachments'
        ordering = ['-attachment_date', '-created_at']
        verbose_name = 'Driver Attachment'
        verbose_name_plural = 'Driver Attachments'

    def __str__(self):
        return (
            f'Attachment for '
            f'{self.driver.driver_code} — '
            f'{self.attachment_date}'
        )

    @property
    def status(self):
        if not self.is_expiry_applicable:
            return self.Status.DOES_NOT_EXPIRE
        today = timezone.localdate()
        if (
            self.expiry_date is not None
            and self.expiry_date < today
        ):
            return self.Status.EXPIRED
        return self.Status.VALID

    def clean(self):
        errors = {}

        if self.is_expiry_applicable:
            if not self.expiry_date:
                errors['expiry_date'] = (
                    'Expiry date is required '
                    'when expiry is applicable'
                )
        else:
            self.expiry_date = None

        if not self.file_notes or \
           not str(self.file_notes).strip():
            errors['file_notes'] = 'File notes are required'

        if self.attachment_file:
            try:
                ext = os.path.splitext(
                    self.attachment_file.name
                )[1].lower()
                if ext not in self._ALLOWED_EXTENSIONS:
                    errors['attachment_file'] = (
                        'Allowed: PDF, JPG, PNG, DOC, DOCX'
                    )
                elif (
                    self.attachment_file.size
                    > self.ATTACHMENT_MAX_SIZE_BYTES
                ):
                    size_mb = round(
                        self.attachment_file.size
                        / 1024 / 1024,
                        1,
                    )
                    errors['attachment_file'] = (
                        f'Max size 10MB. '
                        f'Your file: {size_mb}MB'
                    )
            except AttributeError:
                pass

        if errors:
            raise ValidationError(errors)


class DriverSettings(models.Model):
    """
    Singleton tenant-level driver configuration.
    Not per-driver — applies to the whole tenant.
    """

    class DefaultStatus(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        SUSPENDED = 'Suspended', 'Suspended'
        INACTIVE = 'Inactive', 'Inactive'

    settings_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    default_driver_status = models.CharField(
        max_length=20,
        choices=DefaultStatus.choices,
        default=DefaultStatus.ACTIVE,
        verbose_name=_('Default Driver Status'),
        help_text=_('Status assigned to newly created driver records.'),
    )
    document_expiry_alert_days = models.PositiveIntegerField(
        default=30,
        verbose_name=_('Document Expiry Reminder Days'),
        help_text=_('Days before document expiry alerts.'),
    )
    driver_assignment_required = models.BooleanField(
        default=False,
        verbose_name=_('Driver Assignment Required for Truck'),
        help_text=_('Truck cannot be dispatched without an assigned driver.'),
    )
    document_upload_mandatory = models.BooleanField(
        default=False,
        help_text=_(
            'If enabled, drivers cannot be set to Active without core identity documents.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_driver_settings'
        verbose_name = 'Driver Settings'
        verbose_name_plural = 'Driver Settings'

    def __str__(self):
        return 'Driver Settings'

    @classmethod
    def get_or_create_singleton(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj


class DriverTreasury(models.Model):

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    objects = models.Manager()

    class ActiveManager(models.Manager):
        def get_queryset(self):
            return super().get_queryset().filter(
                status=DriverTreasury.Status.ACTIVE
            )

    active_objects = ActiveManager()

    treasury_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    treasury_code = models.CharField(
        max_length=64,
        unique=True,
    )
    treasury_sequence = models.PositiveIntegerField(
        default=0,
    )
    driver = models.ForeignKey(
        DriverMaster,
        on_delete=models.PROTECT,
        related_name='treasuries',
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    current_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_driver_treasury'
        ordering = ['-created_at']
        verbose_name = 'Driver Treasury'
        verbose_name_plural = 'Driver Treasuries'

    def __str__(self):
        return (
            f'{self.treasury_code} — '
            f'{self.driver.arabic_name}'
        )

    def recalculate_balance(self):
        """
        Recalculate current_balance from all transactions.
        Debit increases wallet (cash in); Credit decreases (cash out).
        """
        from django.db.models import Sum
        credits = self.transactions.filter(
            transaction_type=
            DriverTreasuryTransaction.TransactionType.CREDIT
        ).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        debits = self.transactions.filter(
            transaction_type=
            DriverTreasuryTransaction.TransactionType.DEBIT
        ).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        self.current_balance = debits - credits
        self.save(update_fields=['current_balance'])

    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}
        if not self.driver_id:
            errors['driver'] = 'Driver is required'
        if errors:
            raise ValidationError(errors)


class DriverTreasuryTransaction(models.Model):

    class TransactionType(models.TextChoices):
        CREDIT = 'Credit', 'Credit'
        DEBIT = 'Debit', 'Debit'

    class TransactionCategory(models.TextChoices):
        CLIENT_COLLECTION = (
            'Client Collection',
            'Client Collection',
        )
        CUSTODY_COLLECTION = (
            'Custody Collection',
            'Custody Collection',
        )

    transaction_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    transaction_no = models.CharField(
        max_length=64,
        unique=True,
    )
    transaction_sequence = models.PositiveIntegerField(
        default=0,
    )
    transaction_date = models.DateTimeField()
    driver_treasury = models.ForeignKey(
        DriverTreasury,
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    transaction_type = models.CharField(
        max_length=10,
        choices=TransactionType.choices,
    )
    transaction_category = models.CharField(
        max_length=30,
        choices=TransactionCategory.choices,
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    shipment = models.ForeignKey(
        'TenantShipment',
        on_delete=models.PROTECT,
        related_name='treasury_transactions',
        null=True,
        blank=True,
    )
    operation_action_log = models.ForeignKey(
        'TenantOperationActionLog',
        on_delete=models.SET_NULL,
        related_name='treasury_transactions',
        null=True,
        blank=True,
    )
    description = models.TextField(
        blank=True,
        default='',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_driver_treasury_transactions'
        ordering = ['-transaction_date', '-created_at']
        verbose_name = 'Driver Treasury Transaction'
        verbose_name_plural = 'Driver Treasury Transactions'
        indexes = [
            models.Index(
                fields=['shipment'],
                name='tenant_dtt_shipment_idx',
            ),
            models.Index(
                fields=['operation_action_log'],
                name='tenant_dtt_action_log_idx',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['driver_treasury', 'shipment', 'transaction_category'],
                condition=models.Q(
                    transaction_category='Client Collection',
                    transaction_type='Debit',
                    shipment__isnull=False,
                ),
                name='tenant_dtt_unique_cod_per_wallet_shipment',
            ),
        ]

    def __str__(self):
        return (
            f'{self.transaction_no} — '
            f'{self.transaction_type} '
            f'{self.amount}'
        )

    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}
        if self.amount is not None and self.amount < 0:
            errors['amount'] = (
                'Amount must be 0 or greater'
            )
        if not self.transaction_date:
            errors['transaction_date'] = (
                'Transaction date is required'
            )
        if self.shipment_id and self.driver_treasury_id:
            shipment_driver_id = getattr(self.shipment, 'driver_id', None)
            treasury_driver_id = getattr(
                self.driver_treasury, 'driver_id', None
            )
            if (
                shipment_driver_id
                and treasury_driver_id
                and shipment_driver_id != treasury_driver_id
            ):
                errors['shipment'] = (
                    'Shipment driver must match the treasury wallet driver.'
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Recalculate treasury balance after every save
        if self.driver_treasury_id:
            self.driver_treasury.recalculate_balance()

    def delete(self, *args, **kwargs):
        treasury = self.driver_treasury
        super().delete(*args, **kwargs)
        # Recalculate after delete to reverse impact
        if treasury:
            treasury.recalculate_balance()


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
    file = models.FileField(upload_to=cargo_master_attachment_upload_to)
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
        Has Customs is True when origin and destination are in the same country.
        Missing country id -> False.
        """
        oc = getattr(origin, 'country_id', None)
        dc = getattr(destination, 'country_id', None)
        return bool(oc and dc and oc == dc)

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


class TenantServiceItemMaster(models.Model):
    """SV-001 Service item master (service/trip pricing item)."""

    class ServiceType(models.TextChoices):
        SERVICE = 'Service', 'Service'
        TRIP = 'Trip', 'Trip'

    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    service_item_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_code = models.CharField(max_length=64, unique=True)
    service_sequence = models.PositiveIntegerField(default=0)
    service_type = models.CharField(max_length=12, choices=ServiceType.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    english_name = models.CharField(max_length=200)
    arabic_name = models.CharField(max_length=200, blank=True, default='')
    category_name = models.CharField(max_length=200)
    route = models.ForeignKey(
        TenantRouteMaster,
        on_delete=models.PROTECT,
        related_name='service_items',
        null=True,
        blank=True,
    )
    sell_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    outbound_sell_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    inbound_sell_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_service_item_master'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['service_type', 'status'], name='svc_item_type_status_idx'),
        ]

    def __str__(self):
        return f'{self.service_code} — {self.english_name}'

    def clean(self):
        errors = {}
        if not (self.english_name or '').strip():
            errors['english_name'] = [_('English name is required.')]
        if not (self.category_name or '').strip():
            errors['category_name'] = [_('Category is required.')]

        if self.sell_price is not None and self.sell_price < 0:
            errors['sell_price'] = [_('Sell price must be zero or greater.')]

        if self.service_type == self.ServiceType.TRIP:
            if not self.route_id:
                errors['route'] = [_('Route is required for Trip service type.')]
            if self.outbound_sell_price is None:
                errors['outbound_sell_price'] = [_('Outbound sell price is required for Trip.')]
            elif self.outbound_sell_price < 0:
                errors['outbound_sell_price'] = [_('Outbound sell price must be zero or greater.')]
            if self.inbound_sell_price is None:
                errors['inbound_sell_price'] = [_('Inbound sell price is required for Trip.')]
            elif self.inbound_sell_price < 0:
                errors['inbound_sell_price'] = [_('Inbound sell price must be zero or greater.')]
        else:
            self.route = None
            self.outbound_sell_price = None
            self.inbound_sell_price = None

        if errors:
            raise ValidationError(errors)


class TenantPriceList(models.Model):
    """PL-001 client-specific price list header."""

    class Status(models.TextChoices):
        DRAFT = 'Draft', 'Draft'
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    price_list_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    price_list_code = models.CharField(max_length=64, unique=True)
    price_list_sequence = models.PositiveIntegerField(default=0)
    price_list_name = models.CharField(max_length=200)
    client_account = models.ForeignKey(
        TenantClientAccount,
        on_delete=models.PROTECT,
        related_name='price_lists',
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    base_currency = models.CharField(max_length=10, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_price_list'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['client_account'],
                condition=Q(status='Active'),
                name='tenant_price_list_one_active_per_client_uq',
            ),
        ]
        indexes = [
            models.Index(fields=['client_account', 'status'], name='price_list_client_status_idx'),
        ]

    def __str__(self):
        return f'{self.price_list_code} — {self.price_list_name}'

    def clean(self):
        errors = {}
        if not (self.price_list_name or '').strip():
            errors['price_list_name'] = [_('Price list name is required.')]
        if self.client_account_id:
            if self.client_account.status != TenantClientAccount.Status.ACTIVE:
                errors['client_account'] = [_('Client account must be Active.')]
        else:
            errors['client_account'] = [_('Client account is required.')]
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            errors['effective_to'] = [_('Effective To must be on or after Effective From.')]
        if errors:
            raise ValidationError(errors)

    @classmethod
    def resolve_price_override(cls, *, client_account_id, service_item, trip_type=None, on_date=None):
        """
        Price precedence:
        1) Active client-specific price-list line override (if effective window matches)
        2) Fallback to service item base price

        Returns dict:
        {
          "source": "price_list_override" | "service_item_base",
          "sell_price": Decimal,
          "buy_price": Decimal | None,
          "price_list_id": UUID | None,
          "price_list_code": str | None,
        }
        """
        check_date = on_date or timezone.localdate()
        active_lists = (
            cls.objects.filter(
                client_account_id=client_account_id,
                status=cls.Status.ACTIVE,
            )
            .filter(
                Q(effective_from__isnull=True) | Q(effective_from__lte=check_date),
                Q(effective_to__isnull=True) | Q(effective_to__gte=check_date),
            )
            .order_by('-effective_from', '-created_at')
        )
        active_price_list = active_lists.first()
        if active_price_list:
            if service_item.service_type == TenantServiceItemMaster.ServiceType.TRIP and trip_type:
                trip_line = TenantPriceListTripLine.objects.filter(
                    price_list=active_price_list,
                    trip_service=service_item,
                    trip_type=trip_type,
                ).first()
                if trip_line:
                    return {
                        'source': 'price_list_override',
                        'sell_price': trip_line.sell_price_override,
                        'buy_price': trip_line.buy_price_override,
                        'price_list_id': active_price_list.price_list_id,
                        'price_list_code': active_price_list.price_list_code,
                    }
            elif service_item.service_type == TenantServiceItemMaster.ServiceType.SERVICE:
                service_line = TenantPriceListServiceLine.objects.filter(
                    price_list=active_price_list,
                    service_item=service_item,
                ).first()
                if service_line:
                    return {
                        'source': 'price_list_override',
                        'sell_price': service_line.sell_price_override,
                        'buy_price': service_line.buy_price_override,
                        'price_list_id': active_price_list.price_list_id,
                        'price_list_code': active_price_list.price_list_code,
                    }

        return {
            'source': 'service_item_base',
            'sell_price': service_item.sell_price,
            'buy_price': None,
            'price_list_id': None,
            'price_list_code': None,
        }


class TenantPriceListTripLine(models.Model):
    """Trip service override lines for a client price list."""

    class TripType(models.TextChoices):
        ONE_WAY = 'One-Way', 'One-Way'
        ROUND = 'Round', 'Round'

    line_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    price_list = models.ForeignKey(
        TenantPriceList,
        on_delete=models.CASCADE,
        related_name='trip_lines',
    )
    trip_service = models.ForeignKey(
        TenantServiceItemMaster,
        on_delete=models.PROTECT,
        related_name='price_list_trip_lines',
    )
    trip_type = models.CharField(max_length=12, choices=TripType.choices)
    sell_price_override = models.DecimalField(max_digits=14, decimal_places=2)
    buy_price_override = models.DecimalField(max_digits=14, decimal_places=2)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_price_list_trip_line'
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['price_list', 'trip_service', 'trip_type'],
                name='tenant_price_list_trip_line_uq',
            ),
        ]

    def __str__(self):
        return f'{self.price_list.price_list_code} / {self.trip_service.service_code} / {self.trip_type}'

    def clean(self):
        errors = {}
        if self.sell_price_override is None or self.sell_price_override < 0:
            errors['sell_price_override'] = [_('Sell price override must be zero or greater.')]
        if self.buy_price_override is None or self.buy_price_override < 0:
            errors['buy_price_override'] = [_('Buy price override must be zero or greater.')]
        if self.trip_service_id:
            if self.trip_service.service_type != TenantServiceItemMaster.ServiceType.TRIP:
                errors['trip_service'] = [_('Trip service must have Service Type = Trip.')]
            if self.trip_service.status != TenantServiceItemMaster.Status.ACTIVE:
                errors['trip_service'] = [_('Trip service must be Active.')]
        else:
            errors['trip_service'] = [_('Trip service is required.')]
        if errors:
            raise ValidationError(errors)


class TenantPriceListServiceLine(models.Model):
    """Service/charge override lines for a client price list."""

    line_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    price_list = models.ForeignKey(
        TenantPriceList,
        on_delete=models.CASCADE,
        related_name='service_lines',
    )
    service_item = models.ForeignKey(
        TenantServiceItemMaster,
        on_delete=models.PROTECT,
        related_name='price_list_service_lines',
    )
    sell_price_override = models.DecimalField(max_digits=14, decimal_places=2)
    buy_price_override = models.DecimalField(max_digits=14, decimal_places=2)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_price_list_service_line'
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['price_list', 'service_item'],
                name='tenant_price_list_service_line_uq',
            ),
        ]

    def __str__(self):
        return f'{self.price_list.price_list_code} / {self.service_item.service_code}'

    def clean(self):
        errors = {}
        if self.sell_price_override is None or self.sell_price_override < 0:
            errors['sell_price_override'] = [_('Sell price override must be zero or greater.')]
        if self.buy_price_override is None or self.buy_price_override < 0:
            errors['buy_price_override'] = [_('Buy price override must be zero or greater.')]
        if self.service_item_id:
            if self.service_item.service_type != TenantServiceItemMaster.ServiceType.SERVICE:
                errors['service_item'] = [_('Service item must have Service Type = Service.')]
            if self.service_item.status != TenantServiceItemMaster.Status.ACTIVE:
                errors['service_item'] = [_('Service item must be Active.')]
        else:
            errors['service_item'] = [_('Service item is required.')]
        if errors:
            raise ValidationError(errors)


class SalesInvoiceReport(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'Draft', 'Draft'
        VERIFIED = 'Verified', 'Verified'
        CONVERTED = 'Converted', 'Converted'

    report_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report_no = models.CharField(max_length=64, unique=True)
    report_sequence = models.PositiveIntegerField(default=0)
    client = models.ForeignKey(
        TenantClientAccount,
        on_delete=models.PROTECT,
        related_name='sales_invoice_reports',
    )
    report_date = models.DateField(default=timezone.localdate)
    booking_date_from = models.DateField()
    booking_date_to = models.DateField()
    currency = models.CharField(max_length=10, blank=True, default='')
    total_freight_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_surcharge_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    sales_invoice_ref = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text='FK-ready reference to Sales Invoice (model pending).',
    )
    remarks = models.TextField(blank=True, default='')
    auto_post = models.BooleanField(
        default=False,
        help_text='When enabled, child lines are populated from the operational eligibility sweep.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=200, blank=True, default='')
    updated_by = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        db_table = 'tenant_sales_invoice_report'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['report_no'], name='sir_report_no_idx'),
            models.Index(fields=['client', 'status'], name='sir_client_status_idx'),
            models.Index(fields=['booking_date_from', 'booking_date_to'], name='sir_booking_period_idx'),
        ]

    def __str__(self):
        return self.report_no

    def clean(self):
        errors = {}
        if self.booking_date_from and self.booking_date_to:
            if self.booking_date_from > self.booking_date_to:
                errors['booking_date_to'] = _('Booking date to must be on/after booking date from.')

        if self.client_id:
            if self.client.status != TenantClientAccount.Status.ACTIVE:
                errors['client'] = _('Only active client accounts can be selected.')
        else:
            errors['client'] = _('Client is required.')

        if self.pk:
            prev = SalesInvoiceReport.objects.filter(pk=self.pk).only('status').first()
            if prev and prev.status == self.Status.CONVERTED:
                errors['status'] = _('Converted reports are locked from editing.')

        if errors:
            raise ValidationError(errors)

    @property
    def is_fully_locked(self):
        return self.status == self.Status.CONVERTED

    @property
    def is_partially_locked(self):
        return self.status == self.Status.VERIFIED

    def recalculate_totals(self, *, save=True):
        freight_total = (
            self.booking_lines.aggregate(total=Sum('sell_price')).get('total')
            or Decimal('0')
        )
        surcharge_total = (
            self.surcharge_lines.aggregate(total=Sum('amount')).get('total')
            or Decimal('0')
        )
        self.total_freight_amount = freight_total
        self.total_surcharge_amount = surcharge_total
        if save and self.pk:
            type(self).objects.filter(pk=self.pk).update(
                total_freight_amount=freight_total,
                total_surcharge_amount=surcharge_total,
                updated_at=timezone.now(),
            )

    def save(self, *args, **kwargs):
        # Header totals are system-derived and not user-editable.
        self.total_freight_amount = Decimal(self.total_freight_amount or 0)
        self.total_surcharge_amount = Decimal(self.total_surcharge_amount or 0)
        super().save(*args, **kwargs)


class SalesInvoiceReportBooking(models.Model):
    line_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    line_no = models.PositiveIntegerField()
    report = models.ForeignKey(
        SalesInvoiceReport,
        on_delete=models.CASCADE,
        related_name='booking_lines',
    )
    booking = models.ForeignKey(
        'TenantBooking',
        on_delete=models.PROTECT,
        related_name='sales_invoice_report_lines',
        null=True,
        blank=True,
    )
    so_ref = models.CharField(max_length=120, blank=True, default='')
    service_name = models.CharField(max_length=200, blank=True, default='')
    trip_type = models.CharField(max_length=50, blank=True, default='')
    sell_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    booking_status = models.CharField(
        max_length=30,
        blank=True,
        default='',
        help_text='Snapshot of booking execution status at line capture.',
    )

    class Meta:
        db_table = 'tenant_sales_invoice_report_booking'
        ordering = ['line_no']
        constraints = [
            models.UniqueConstraint(fields=['report', 'line_no'], name='sir_booking_line_no_uq'),
            models.UniqueConstraint(
                fields=['report', 'booking'],
                condition=Q(booking__isnull=False),
                name='sir_unique_booking_per_report_uq',
            ),
        ]
        indexes = [
            models.Index(fields=['report', 'line_no'], name='sir_booking_report_line_idx'),
            models.Index(fields=['booking'], name='sir_booking_fk_idx'),
        ]

    def clean(self):
        errors = {}
        if self.booking_status and self.booking_status.lower() != 'executed':
            errors['booking_status'] = _('Only executed bookings can be added.')
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.report.recalculate_totals(save=True)

    def delete(self, *args, **kwargs):
        report = self.report
        super().delete(*args, **kwargs)
        report.recalculate_totals(save=True)


class SalesInvoiceReportSurcharge(models.Model):
    line_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    line_no = models.PositiveIntegerField()
    report = models.ForeignKey(
        SalesInvoiceReport,
        on_delete=models.CASCADE,
        related_name='surcharge_lines',
    )
    surcharge = models.ForeignKey(
        'TenantShipmentSurcharge',
        on_delete=models.PROTECT,
        related_name='sales_invoice_report_lines',
        null=True,
        blank=True,
    )
    booking = models.ForeignKey(
        'TenantBooking',
        on_delete=models.PROTECT,
        related_name='sales_invoice_report_surcharge_lines',
        null=True,
        blank=True,
    )
    shipment = models.ForeignKey(
        'TenantShipment',
        on_delete=models.PROTECT,
        related_name='sales_invoice_report_surcharge_lines',
        null=True,
        blank=True,
    )
    surcharge_type = models.CharField(max_length=120, blank=True, default='')
    service_name = models.CharField(max_length=200, blank=True, default='')
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        db_table = 'tenant_sales_invoice_report_surcharge'
        ordering = ['line_no']
        constraints = [
            models.UniqueConstraint(fields=['report', 'line_no'], name='sir_surcharge_line_no_uq'),
        ]
        indexes = [
            models.Index(fields=['report', 'line_no'], name='sir_surcharge_report_line_idx'),
            models.Index(fields=['surcharge'], name='sir_surcharge_fk_idx'),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.report.recalculate_totals(save=True)

    def delete(self, *args, **kwargs):
        report = self.report
        super().delete(*args, **kwargs)
        report.recalculate_totals(save=True)


class SalesInvoiceReportShipment(models.Model):
    line_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    line_no = models.PositiveIntegerField()
    report = models.ForeignKey(
        SalesInvoiceReport,
        on_delete=models.CASCADE,
        related_name='shipment_lines',
    )
    shipment = models.ForeignKey(
        'TenantShipment',
        on_delete=models.PROTECT,
        related_name='sales_invoice_report_lines',
        null=True,
        blank=True,
    )
    booking = models.ForeignKey(
        'TenantBooking',
        on_delete=models.PROTECT,
        related_name='sales_invoice_report_shipment_lines',
        null=True,
        blank=True,
    )
    shipment_date = models.DateField(null=True, blank=True)
    from_location = models.CharField(max_length=200, blank=True, default='')
    to_location = models.CharField(max_length=200, blank=True, default='')
    truck_plate = models.CharField(max_length=120, blank=True, default='')
    customer_ref_docs = models.TextField(blank=True, default='')
    pod_date = models.DateField(null=True, blank=True)
    pod_status = models.CharField(max_length=30, blank=True, default='')

    class Meta:
        db_table = 'tenant_sales_invoice_report_shipment'
        ordering = ['line_no']
        constraints = [
            models.UniqueConstraint(fields=['report', 'line_no'], name='sir_shipment_line_no_uq'),
        ]
        indexes = [
            models.Index(fields=['report', 'line_no'], name='sir_shipment_report_line_idx'),
            models.Index(fields=['shipment'], name='sir_shipment_fk_idx'),
        ]


class ActiveTenantUserManager(models.Manager):
    """Default queryset: exclude soft-deleted tenant workspace users."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class AllTenantUserManager(models.Manager):
    """Unfiltered queryset (includes soft-deleted rows)."""

    def get_queryset(self):
        return super().get_queryset()


class TenantUser(models.Model):
    """Tenant-scoped internal users (stored per tenant schema).

    ``objects`` excludes soft-deleted rows (normal UI and listings).
    Use ``all_objects`` when resolving by email/pk across delete boundaries
    (login, uniqueness vs DB, audit labels).
    """

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
    last_login_ip = models.CharField(max_length=45, blank=True, default='')
    last_failed_login_at = models.DateTimeField(null=True, blank=True)
    login_attempts = models.PositiveIntegerField(default=0)
    mobile_token_version = models.PositiveIntegerField(
        default=0,
        help_text='Incremented on password change to invalidate outstanding mobile JWTs.',
    )
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tenant_users_deleted',
        db_constraint=False,
    )

    objects = ActiveTenantUserManager()
    all_objects = AllTenantUserManager()

    class Meta:
        db_table = 'tenant_users'
        ordering = ['-created_at']
        base_manager_name = 'all_objects'
        indexes = [
            models.Index(
                fields=['is_deleted', 'status'],
                name='tu_deleted_status_idx',
            ),
        ]

    def __str__(self):
        return f'{self.full_name} ({self.username})'

    @property
    def is_active_user(self):
        """True when the row is not soft-deleted and status is Active (existing lifecycle semantics)."""
        return not self.is_deleted and self.status == self.Status.ACTIVE

    def soft_delete(
        self,
        deleted_by=None,
        save=True,
        *,
        revoke_tenant_workspace_sessions=True,
        mobile_tokens_to_blacklist=None,
    ):
        """Mark the tenant user as soft-deleted and inactive; preserves row for audit and restore.

        After a successful ``save``, best-effort:
        - Revokes tenant **portal** Redis sessions for this user (web sub-user).
        - Optionally blacklists mobile JWT JTIs (``mobile_tokens_to_blacklist``), each item
          ``{'jti': str, 'exp': int | None}`` for access/refresh tokens when the caller holds them.

        Redis / blacklist failures never prevent soft-delete from persisting.
        """
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.status = self.Status.INACTIVE
        if deleted_by is not None:
            self.deleted_by = deleted_by
        if save:
            self.save(
                update_fields=[
                    'is_deleted',
                    'deleted_at',
                    'deleted_by',
                    'status',
                    'updated_at',
                ],
            )
            self._after_soft_delete_side_effects(
                revoke_tenant_workspace_sessions=revoke_tenant_workspace_sessions,
                mobile_tokens_to_blacklist=mobile_tokens_to_blacklist,
            )

    def _after_soft_delete_side_effects(
        self,
        *,
        revoke_tenant_workspace_sessions,
        mobile_tokens_to_blacklist,
    ):
        if revoke_tenant_workspace_sessions:
            self._revoke_tenant_workspace_redis_sessions_best_effort()
        if mobile_tokens_to_blacklist:
            try:
                from mobile_api.helpers.auth import blacklist_token_jti

                for entry in mobile_tokens_to_blacklist:
                    if not isinstance(entry, dict):
                        continue
                    jti = (entry.get('jti') or '').strip()
                    if not jti:
                        continue
                    blacklist_token_jti(jti=jti, exp_ts=entry.get('exp'))
            except Exception:
                pass

    def _revoke_tenant_workspace_redis_sessions_best_effort(self):
        """Revoke tenant portal Redis rows for this ``TenantUser`` when DB connection is on tenant schema."""
        from django.db import connection

        schema = getattr(connection, 'schema_name', None) or ''
        if not schema or schema == 'public':
            return
        try:
            from django_tenants.utils import schema_context

            from iroad_tenants.models import TenantRegistry
            from superadmin.redis_helpers import (
                revoke_tenant_workspace_sessions_for_user_reference,
            )

            with schema_context('public'):
                reg = TenantRegistry.objects.filter(schema_name=schema).first()
            if not reg:
                return
            revoke_tenant_workspace_sessions_for_user_reference(
                str(reg.tenant_profile_id),
                str(self.pk),
            )
        except Exception:
            pass

    def restore(self, save=True):
        """Clear soft-delete flags; does not change ``status`` (caller may re-activate separately)."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        if save:
            self.save(
                update_fields=[
                    'is_deleted',
                    'deleted_at',
                    'deleted_by',
                    'updated_at',
                ],
            )


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


class TenantBooking(models.Model):
    """BK-001 booking header record for tenant operations."""

    class Status(models.TextChoices):
        DRAFT = 'Draft', 'Draft'
        CONFIRMED = 'Confirmed', 'Confirmed'
        CANCELLED = 'Cancelled', 'Cancelled'

    booking_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_no = models.CharField(max_length=64, unique=True)
    booking_sequence = models.PositiveIntegerField(default=0)
    creation_date = models.DateField(default=date.today)
    booking_date = models.DateField(default=date.today)
    is_scheduled = models.BooleanField(default=False)
    execution_date = models.DateField(null=True, blank=True)
    booking_status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    client_account = models.ForeignKey(
        TenantClientAccount,
        on_delete=models.PROTECT,
        related_name='bookings',
    )
    price_list = models.ForeignKey(
        TenantPriceList,
        on_delete=models.PROTECT,
        related_name='bookings',
        null=True,
        blank=True,
    )
    service_item = models.ForeignKey(
        TenantServiceItemMaster,
        on_delete=models.PROTECT,
        related_name='bookings',
        null=True,
        blank=True,
    )
    route = models.ForeignKey(
        TenantRouteMaster,
        on_delete=models.PROTECT,
        related_name='bookings',
        null=True,
        blank=True,
    )
    route_direction = models.CharField(max_length=12, blank=True, default='forward')
    route_display = models.CharField(max_length=255, blank=True, default='')
    loading_booking_item = models.CharField(max_length=20, blank=True, default='')
    loading_address = models.ForeignKey(
        TenantAddressMaster,
        on_delete=models.SET_NULL,
        related_name='loading_bookings',
        null=True,
        blank=True,
    )
    delivery_booking_item = models.CharField(max_length=20, blank=True, default='')
    delivery_address = models.ForeignKey(
        TenantAddressMaster,
        on_delete=models.SET_NULL,
        related_name='delivery_bookings',
        null=True,
        blank=True,
    )
    order_type = models.CharField(max_length=20, blank=True, default='')
    trip_type = models.CharField(max_length=20, blank=True, default='')
    sell_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sourcing_mode = models.CharField(max_length=20, blank=True, default='')
    pod_type = models.CharField(max_length=30, blank=True, default='')
    pod_status = models.CharField(max_length=30, blank=True, default='')
    assigned_truck = models.ForeignKey(
        TruckMaster,
        on_delete=models.SET_NULL,
        related_name='assigned_bookings',
        null=True,
        blank=True,
    )
    assigned_driver = models.ForeignKey(
        DriverMaster,
        on_delete=models.SET_NULL,
        related_name='assigned_bookings',
        null=True,
        blank=True,
    )
    booking_line_backload_truck = models.ForeignKey(
        TruckMaster,
        on_delete=models.SET_NULL,
        related_name='backload_assigned_bookings',
        null=True,
        blank=True,
    )
    booking_line_backload_driver = models.ForeignKey(
        DriverMaster,
        on_delete=models.SET_NULL,
        related_name='backload_assigned_bookings',
        null=True,
        blank=True,
    )
    booking_line_cod_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    booking_line_pod_doc_count = models.PositiveIntegerField(default=0)
    booking_line_backload_cod_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    booking_line_backload_pod_doc_count = models.PositiveIntegerField(default=0)
    cargo_booking_item = models.CharField(max_length=20, blank=True, default='')
    cargo = models.ForeignKey(
        TenantCargoMaster,
        on_delete=models.SET_NULL,
        related_name='bookings',
        null=True,
        blank=True,
    )
    cargo_weight = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cargo_unit = models.CharField(max_length=50, blank=True, default='')
    cargo_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cargo_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cargo_weight = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    container_no = models.CharField(max_length=120, blank=True, default='')
    booking_attachment = models.FileField(
        upload_to=booking_attachment_upload_to,
        blank=True,
        null=True,
        max_length=500,
    )
    booking_instructions = models.TextField(blank=True, default='')
    sales_invoice_report = models.ForeignKey(
        'SalesInvoiceReport',
        on_delete=models.SET_NULL,
        related_name='linked_bookings',
        null=True,
        blank=True,
    )
    sales_report_status = models.CharField(
        max_length=30,
        blank=True,
        default='',
        help_text='Derived from linked Sales Invoice Report (Pending/Submitted/Invoiced).',
    )
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_bookings'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['booking_no'], name='tenant_booking_no_idx'),
            models.Index(fields=['client_account', 'booking_status'], name='tenant_bkg_client_status_idx'),
            models.Index(
                fields=['assigned_driver'],
                name='tenant_book_assign_drv_idx',
            ),
        ]

    def __str__(self):
        return self.booking_no



class TenantShipment(models.Model):
    """SH-001 Shipment execution record (Phase 1 foundation)."""

    class ShipmentStatus(models.TextChoices):
        LOADED = 'Loaded', 'Loaded'
        IN_TRANSIT = 'In Transit', 'In Transit'
        AT_DELIVERY = 'At Delivery', 'At Delivery'
        POD_SUBMITTED = 'POD Submitted', 'POD Submitted'
        DELIVERED = 'Delivered', 'Delivered'
        CLOSED = 'Closed', 'Closed'
        CANCELLED = 'Cancelled', 'Cancelled'
        CREATED = 'Created', 'Created'  # legacy rows; new shipments use Loaded

    class PodType(models.TextChoices):
        DIGITAL = 'Digital', 'Digital'
        SOFT = 'Soft', 'Soft'
        HARD = 'Hard', 'Hard'

    class PodStatus(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        HARD_COPY_RECEIVED = 'Hard Copy Received', 'Hard Copy Received'
        COMPLIANT = 'Compliant', 'Compliant'
        NOT_COMPLIANT = 'Not Compliant', 'Not Compliant'

    class SourcingMode(models.TextChoices):
        IN_SOURCE = 'In-Source', 'In-Source'
        OUT_SOURCE = 'Out-Source', 'Out-Source'

    class CollectionStatus(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        COLLECTED = 'Collected', 'Collected'

    shipment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shipment_no = models.CharField(max_length=64, unique=True)
    shipment_sequence = models.PositiveIntegerField(default=0)
    shipment_date = models.DateField(default=date.today)
    shipment_status = models.CharField(
        max_length=20,
        choices=ShipmentStatus.choices,
        default=ShipmentStatus.LOADED,
    )
    booking = models.ForeignKey(
        'TenantBooking',
        on_delete=models.PROTECT,
        related_name='shipments',
        null=True,
        blank=True,
    )
    client_account = models.ForeignKey(
        'TenantClientAccount',
        on_delete=models.PROTECT,
        related_name='shipments',
        null=True,
        blank=True,
    )
    booking_item_ref = models.CharField(max_length=64)
    booking_item_type = models.CharField(max_length=20, blank=True, default='')
    sourcing_mode = models.CharField(max_length=20, choices=SourcingMode.choices)
    trip_type = models.CharField(max_length=20, blank=True, default='')
    route_display = models.CharField(max_length=120, blank=True, default='')
    order_type = models.CharField(max_length=20, blank=True, default='')
    loading_address = models.ForeignKey(
        'TenantAddressMaster',
        on_delete=models.SET_NULL,
        related_name='shipments_as_loading',
        null=True,
        blank=True,
    )
    delivery_address = models.ForeignKey(
        'TenantAddressMaster',
        on_delete=models.SET_NULL,
        related_name='shipments_as_delivery',
        null=True,
        blank=True,
    )
    cargo_booking_item = models.CharField(max_length=20, blank=True, default='')
    cargo = models.ForeignKey(
        'TenantCargoMaster',
        on_delete=models.SET_NULL,
        related_name='shipments',
        null=True,
        blank=True,
    )
    cargo_weight = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cargo_unit = models.CharField(max_length=50, blank=True, default='')
    cargo_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    sales_order_ref = models.CharField(max_length=64, blank=True, default='')
    sales_order_item_ref = models.CharField(max_length=64, blank=True, default='')
    vendor_account_ref = models.CharField(max_length=64, blank=True, default='')
    purchase_order_ref = models.CharField(max_length=64, blank=True, default='')
    purchase_order_item_ref = models.CharField(max_length=64, blank=True, default='')

    truck = models.ForeignKey(
        TruckMaster,
        on_delete=models.PROTECT,
        related_name='shipments',
        null=True,
        blank=True,
    )
    driver = models.ForeignKey(
        'DriverMaster',
        on_delete=models.PROTECT,
        related_name='shipments',
        null=True,
        blank=True,
    )
    pod_type = models.CharField(max_length=12, choices=PodType.choices, default=PodType.DIGITAL)
    pod_status = models.CharField(
        max_length=20,
        choices=PodStatus.choices,
        default=PodStatus.PENDING,
    )
    pod_doc_count = models.PositiveIntegerField(default=0)
    cod_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    collection_status = models.CharField(
        max_length=20,
        choices=CollectionStatus.choices,
        default=CollectionStatus.PENDING,
    )
    mobile_operational_rank = models.SmallIntegerField(
        default=10,
        db_index=True,
        help_text='Mobile job list priority_desc sort key (lower = higher priority).',
    )

    sales_invoice_ref = models.CharField(max_length=64, blank=True, default='')
    sales_invoice_status = models.CharField(max_length=32, blank=True, default='')
    purchase_invoice_ref = models.CharField(max_length=64, blank=True, default='')
    purchase_invoice_status = models.CharField(max_length=32, blank=True, default='')

    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_shipments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['booking', 'booking_item_ref'], name='tenant_shipment_booking_idx'),
            models.Index(fields=['shipment_status'], name='tenant_shipment_status_idx'),
            models.Index(fields=['booking'], name='tenant_shipment_booking_fk_idx'),
            models.Index(fields=['client_account'], name='tenant_shipment_client_fk_idx'),
            models.Index(fields=['driver'], name='tenant_shipment_driver_fk_idx'),
            models.Index(
                fields=['driver', 'shipment_status'],
                name='tenant_ship_driver_status_idx',
            ),
            models.Index(
                fields=['driver', 'updated_at'],
                name='tenant_ship_driver_upd_idx',
            ),
            models.Index(
                fields=['driver', 'shipment_status', '-updated_at'],
                name='tenant_ship_drv_stat_upd_idx',
            ),
            models.Index(
                fields=['booking', 'shipment_status'],
                name='tenant_ship_book_stat_idx',
            ),
            models.Index(
                fields=['shipment_status', 'pod_status'],
                name='tenant_ship_stat_pod_idx',
            ),
            models.Index(
                fields=['shipment_status', 'collection_status'],
                name='tenant_ship_stat_coll_idx',
            ),
            models.Index(
                fields=['driver', 'shipment_no'],
                name='tenant_ship_drv_no_idx',
            ),
            models.Index(
                fields=['driver', 'mobile_operational_rank', '-updated_at'],
                name='tenant_ship_drv_rank_upd_idx',
            ),
        ]

    def apply_truck_default_driver(self):
        if self.truck_id and self.truck and not self.driver_id and self.truck.default_driver_id_id:
            self.driver = self.truck.default_driver_id

    def save(self, *args, **kwargs):
        self.apply_truck_default_driver()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.shipment_no

    def clean(self):
        errors = {}

        if not self.booking_id:
            errors['booking'] = [_('Booking is required.')]
        if not (self.booking_item_ref or '').strip():
            errors['booking_item_ref'] = [_('Booking item is required.')]

        if self.truck_id and self.truck and self.truck.status != TruckMaster.Status.ACTIVE:
            errors['truck'] = [_('Truck must be Active.')]

        if self.driver_id and self.driver and self.driver.driver_status != DriverMaster.Status.ACTIVE:
            errors['driver'] = [_('Driver must be Active.')]

        if self.truck_id and self.sourcing_mode and self.truck:
            if self.sourcing_mode == self.SourcingMode.IN_SOURCE and self.truck.sourcing_mode != TruckMaster.SourcingMode.IN_SOURCE:
                errors['truck'] = [_('In-Source shipment requires an In-Source truck.')]
            if self.sourcing_mode == self.SourcingMode.OUT_SOURCE and self.truck.sourcing_mode != TruckMaster.SourcingMode.OUT_SOURCE:
                errors['truck'] = [_('Out-Source shipment requires an Out-Source truck.')]

        if self.booking_id and self.client_account_id:
            booking_client_id = TenantBooking.objects.filter(
                pk=self.booking_id,
            ).values_list('client_account_id', flat=True).first()
            if booking_client_id and booking_client_id != self.client_account_id:
                errors['client_account'] = [_('Client account must match the linked booking.')]

        if self.shipment_status == self.ShipmentStatus.CANCELLED:
            if self.pk:
                previous = TenantShipment.objects.filter(pk=self.pk).values_list(
                    'shipment_status', flat=True
                ).first()
                cancellable = {
                    self.ShipmentStatus.LOADED,
                    self.ShipmentStatus.CREATED,
                    self.ShipmentStatus.IN_TRANSIT,
                    self.ShipmentStatus.AT_DELIVERY,
                    self.ShipmentStatus.POD_SUBMITTED,
                }
                if previous not in cancellable:
                    errors['shipment_status'] = [
                        _('Cancelled is allowed only before the shipment is closed.'),
                    ]

        if self.order_type.upper() == 'COD':
            if self.shipment_status == self.ShipmentStatus.CLOSED and self.collection_status != self.CollectionStatus.COLLECTED:
                errors['collection_status'] = [
                    _('COD shipment cannot be closed until collection status is Collected.'),
                ]

        if errors:
            raise ValidationError(errors)

    @property
    def total_additional_charges(self):
        return self.surcharges.aggregate(total=models.Sum('subtotal')).get('total') or 0


class TenantShipmentSurcharge(models.Model):
    """Derived surcharge rows linked to shipment."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        CONFIRMED = 'confirmed', 'Confirmed'
        INVOICED = 'invoiced', 'Invoiced'
        CANCELLED = 'cancelled', 'Cancelled'

    surcharge_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_no = models.CharField(max_length=64, unique=True, null=True, blank=True)
    transaction_sequence = models.PositiveIntegerField(default=0)
    transaction_date = models.DateField(default=date.today)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    shipment = models.ForeignKey(
        TenantShipment,
        on_delete=models.CASCADE,
        related_name='surcharges',
    )
    booking = models.ForeignKey(
        'TenantBooking',
        on_delete=models.PROTECT,
        related_name='shipment_surcharges',
        null=True,
        blank=True,
    )
    client_account = models.ForeignKey(
        'TenantClientAccount',
        on_delete=models.PROTECT,
        related_name='shipment_surcharges',
        null=True,
        blank=True,
    )
    service_item = models.ForeignKey(
        'TenantServiceItemMaster',
        on_delete=models.PROTECT,
        related_name='shipment_surcharges',
        null=True,
        blank=True,
    )
    line_no = models.PositiveIntegerField(default=1)
    item_label = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True, default='')
    qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, blank=True, default='SAR')
    reason = models.TextField(blank=True, default='')
    attachment_file = models.FileField(
        upload_to=surcharge_attachment_upload_to,
        max_length=500,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_shipment_surcharges'
        ordering = ['line_no', 'created_at']
        indexes = [
            models.Index(fields=['shipment'], name='tenant_surcharge_shipment_idx'),
            models.Index(fields=['service_item'], name='tenant_surcharge_service_idx'),
            models.Index(fields=['booking'], name='tenant_surcharge_booking_idx'),
            models.Index(fields=['client_account'], name='tenant_surcharge_client_idx'),
            models.Index(fields=['status'], name='tenant_surcharge_status_idx'),
        ]

    def sync_denormalized_refs(self):
        if self.service_item_id:
            label = self.service_item.english_name
            if self.description:
                label = f'{label} - {self.description}'
            self.item_label = label[:120]
        if self.shipment_id:
            shipment = self.shipment
            if shipment.booking_id and not self.booking_id:
                self.booking = shipment.booking
            if shipment.client_account_id and not self.client_account_id:
                self.client_account = shipment.client_account
        if self.client_account_id and not (self.currency or '').strip():
            self.currency = (self.client_account.preferred_currency or 'SAR')[:8]

    def save(self, *args, **kwargs):
        self.sync_denormalized_refs()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.shipment.shipment_no} / {self.item_label}'


class TenantShipmentDocument(models.Model):
    """Shipment document header record."""

    class Status(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        UPLOADED = 'Uploaded', 'Uploaded'
        VERIFIED = 'Verified', 'Verified'
        DRAFT = 'Draft', 'Draft'
        REJECTED = 'Rejected', 'Rejected'

    document_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record_no = models.CharField(max_length=64, unique=True)
    record_sequence = models.PositiveIntegerField(default=0)
    record_date = models.DateField(default=date.today)
    booking = models.ForeignKey(
        'TenantBooking',
        on_delete=models.PROTECT,
        related_name='shipment_documents',
        null=True,
        blank=True,
    )
    shipment = models.ForeignKey(
        'TenantShipment',
        on_delete=models.PROTECT,
        related_name='documents',
        null=True,
        blank=True,
    )
    source_document = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='pod_source_children',
        null=True,
        blank=True,
    )
    receiver_user = models.ForeignKey(
        'TenantUser',
        on_delete=models.SET_NULL,
        related_name='received_shipment_documents',
        null=True,
        blank=True,
    )
    document_type = models.CharField(max_length=64)
    document_ref_no = models.CharField(max_length=120)
    document_date = models.DateField(default=date.today)
    is_delivery_note = models.BooleanField(default=False)
    physical_location = models.CharField(max_length=255, blank=True, default='')
    page_count = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True, default='')
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_shipment_documents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['record_no'], name='tenant_shipdoc_record_idx'),
            models.Index(fields=['status'], name='tenant_shipdoc_status_idx'),
            models.Index(fields=['booking'], name='tenant_shipdoc_booking_idx'),
            models.Index(fields=['shipment'], name='tenant_shipdoc_shipment_idx'),
            models.Index(
                fields=['shipment', 'is_delivery_note', '-updated_at'],
                name='tenant_shipdoc_ship_dn_upd_idx',
            ),
            models.Index(fields=['source_document'], name='tenant_shipdoc_source_idx'),
            models.Index(fields=['receiver_user'], name='tenant_shipdoc_receiver_idx'),
        ]

    def sync_booking_from_shipment(self):
        if self.shipment_id and self.shipment.booking_id and not self.booking_id:
            self.booking = self.shipment.booking

    def sync_from_source_document(self):
        if not self.source_document_id:
            return
        source = self.source_document
        if not source:
            return
        self.document_ref_no = source.document_ref_no
        if source.document_date:
            self.document_date = source.document_date
        if source.page_count:
            self.page_count = source.page_count

    def sync_pod_pages_from_document_pages(self):
        """Mirror OP-DOC document pages to pod_pages for handover/POD integrations."""
        from django.apps import apps

        document_page_model = apps.get_model('tenant_workspace', 'TenantShipmentDocumentPage')
        pod_page_model = apps.get_model('tenant_workspace', 'TenantShipmentPodPage')
        pod_page_model.objects.filter(document=self).delete()
        shipment = self.shipment if self.shipment_id else None
        for page in document_page_model.objects.filter(document=self).order_by('line_no'):
            action_log = None
            extra_ref = (page.extra_ref or '').strip()
            if extra_ref:
                action_log = resolve_operation_action_log_for_pod(extra_ref, shipment=shipment)
            pod_page_model.objects.create(
                document=self,
                line_no=page.line_no,
                doc_page=str(page.physical_page_no),
                source=page.doc_ref_no,
                action_log=action_log,
                physical_location=page.signer_location,
                soft_copy_status=page.completion_status,
                attachment_label=page.attachment_label,
                map_url=page.attachment_storage_path,
            )

    def save(self, *args, **kwargs):
        self.sync_booking_from_shipment()
        self.sync_from_source_document()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.record_no


class TenantShipmentDocumentPage(models.Model):
    """Shipment document page lines (OP-DOC ShipmentDocumentPage)."""

    class CompletionStatus(models.TextChoices):
        COMPLETED = 'Completed', 'Completed'
        NOT_COMPLETED = 'Not Completed', 'Not Completed'

    class SignerLocation(models.TextChoices):
        WITH_DRIVER = 'With Driver', 'With Driver'
        IN_COMPANY = 'In Company', 'In Company'
        WITH_CLIENT = 'With Client', 'With Client'

    page_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        TenantShipmentDocument,
        on_delete=models.CASCADE,
        related_name='document_pages',
    )
    line_no = models.PositiveIntegerField(default=1)
    doc_ref_no = models.CharField(max_length=120, blank=True, default='')
    extra_ref = models.CharField(max_length=120, blank=True, default='')
    physical_page_no = models.PositiveIntegerField(default=1)
    completion_status = models.CharField(
        max_length=20,
        choices=CompletionStatus.choices,
        blank=True,
        default='',
    )
    signer_location = models.CharField(
        max_length=120,
        choices=SignerLocation.choices,
        blank=True,
        default='',
    )
    attachment_storage_path = models.CharField(max_length=500, blank=True, default='')
    attachment_label = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_shipment_document_pages'
        ordering = ['line_no', 'created_at']
        indexes = [
            models.Index(fields=['document', 'line_no'], name='tenant_shipdocpage_doc_ln_idx'),
        ]

    def sync_doc_ref_from_document(self):
        if self.document_id and self.document and not (self.doc_ref_no or '').strip():
            self.doc_ref_no = self.document.document_ref_no

    def save(self, *args, **kwargs):
        self.sync_doc_ref_from_document()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.document.record_no} / Page {self.physical_page_no}'


def resolve_operation_action_log_for_pod(ref, *, shipment=None):
    """Resolve a log_no or UUID string to TenantOperationActionLog for POD lines."""
    from django.apps import apps

    value = str(ref or '').strip()
    if not value:
        return None
    action_log_model = apps.get_model('tenant_workspace', 'TenantOperationActionLog')
    try:
        parsed_id = uuid.UUID(value)
        match = action_log_model.objects.filter(pk=parsed_id).first()
        if match is not None:
            return match
    except ValueError:
        pass
    if shipment is not None:
        match = action_log_model.objects.filter(log_no=value, shipment=shipment).first()
        if match is not None:
            return match
    return action_log_model.objects.filter(log_no=value).first()


class TenantShipmentPodPage(models.Model):
    """Line-level POD page tracking rows under a shipment POD document."""

    page_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        TenantShipmentDocument,
        on_delete=models.CASCADE,
        related_name='pod_pages',
    )
    line_no = models.PositiveIntegerField(default=1)
    source_page = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='pod_lines_referencing',
        null=True,
        blank=True,
    )
    doc_page = models.CharField(max_length=64, blank=True, default='')
    source = models.CharField(max_length=64, blank=True, default='')
    action_log = models.ForeignKey(
        'TenantOperationActionLog',
        on_delete=models.SET_NULL,
        related_name='pod_page_lines',
        null=True,
        blank=True,
    )
    physical_location = models.CharField(max_length=120, blank=True, default='')
    soft_copy_status = models.CharField(max_length=64, blank=True, default='')
    digital_evidence_status = models.CharField(max_length=64, blank=True, default='')
    map_url = models.URLField(blank=True, default='')
    attachment_label = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_shipment_pod_pages'
        ordering = ['line_no', 'created_at']
        indexes = [
            models.Index(fields=['document', 'line_no'], name='tenant_podpage_doc_line_idx'),
            models.Index(fields=['source_page'], name='tenant_podpage_source_idx'),
        ]

    def sync_doc_page_from_source(self):
        if self.source_page_id and self.source_page:
            label = (self.source_page.doc_page or '').strip()
            self.doc_page = label or f'Page-{self.source_page.line_no}'

    def save(self, *args, **kwargs):
        self.sync_doc_page_from_source()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.document.record_no} / Line {self.line_no}'


class TenantDocumentHandover(models.Model):
    """Document handover header transaction."""

    class Status(models.TextChoices):
        DRAFT = 'Draft', 'Draft'
        POSTED = 'Posted', 'Posted'
        CLIENT_RECEIVED = 'Client Received', 'Client Received'
        REJECTED = 'Rejected', 'Rejected'
        MISSING = 'Missing', 'Missing'

    handover_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    handover_no = models.CharField(max_length=64, unique=True)
    handover_sequence = models.PositiveIntegerField(default=0)
    handover_date = models.DateField(default=date.today)
    booking = models.ForeignKey(
        'TenantBooking',
        on_delete=models.PROTECT,
        related_name='document_handovers',
        null=True,
        blank=True,
    )
    shipment = models.ForeignKey(
        'TenantShipment',
        on_delete=models.PROTECT,
        related_name='document_handovers',
        null=True,
        blank=True,
    )
    document = models.ForeignKey(
        'TenantShipmentDocument',
        on_delete=models.SET_NULL,
        related_name='handovers',
        null=True,
        blank=True,
    )
    pod_document = models.ForeignKey(
        'TenantShipmentDocument',
        on_delete=models.SET_NULL,
        related_name='pod_handovers',
        null=True,
        blank=True,
    )
    physical_location = models.CharField(max_length=120, blank=True, default='')
    receiver_user = models.ForeignKey(
        'TenantUser',
        on_delete=models.PROTECT,
        related_name='document_handovers_received',
        null=True,
        blank=True,
    )
    received_user = models.CharField(max_length=120, blank=True, default='')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True, default='')
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_document_handovers'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['handover_no'], name='tenant_doc_ho_no_idx'),
            models.Index(fields=['shipment'], name='tenant_doc_ho_ship_idx'),
            models.Index(fields=['status'], name='tenant_doc_ho_status_idx'),
            models.Index(fields=['booking'], name='tenant_doc_ho_booking_idx'),
        ]

    def sync_booking_from_shipment(self):
        if self.shipment_id and self.shipment.booking_id and not self.booking_id:
            self.booking = self.shipment.booking

    def sync_received_user_label(self):
        if self.receiver_user_id and self.receiver_user:
            label = (self.receiver_user.full_name or self.receiver_user.username or '').strip()
            if self.receiver_user.username and self.receiver_user.username not in label:
                label = f'{label} ({self.receiver_user.username})' if label else self.receiver_user.username
            self.received_user = label

    def save(self, *args, **kwargs):
        self.sync_booking_from_shipment()
        self.sync_received_user_label()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.handover_no


class TenantDocumentHandoverLine(models.Model):
    """Page verification lines under a handover transaction."""

    class PhysicalStatus(models.TextChoices):
        RECEIVED_OK = 'ReceivedOK', 'Received OK'
        MISSING = 'Missing', 'Missing'
        REJECTED = 'Rejected', 'Rejected'

    line_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    handover = models.ForeignKey(
        TenantDocumentHandover,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    line_no = models.PositiveIntegerField(default=1)
    source_page = models.ForeignKey(
        'TenantShipmentPodPage',
        on_delete=models.PROTECT,
        related_name='handover_lines',
        null=True,
        blank=True,
    )
    doc_page = models.CharField(max_length=64, blank=True, default='')
    page_status = models.CharField(max_length=64, blank=True, default='')
    physical_location = models.CharField(max_length=120, blank=True, default='')
    note = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_document_handover_lines'
        ordering = ['line_no', 'created_at']
        indexes = [
            models.Index(fields=['handover', 'line_no'], name='tenant_doc_ho_line_idx'),
            models.Index(fields=['source_page'], name='tenant_doc_ho_srcpage_idx'),
        ]

    def sync_doc_page_from_source(self):
        if self.source_page_id and self.source_page:
            label = (self.source_page.doc_page or '').strip()
            self.doc_page = label or f'Page-{self.source_page.line_no}'

    def save(self, *args, **kwargs):
        self.sync_doc_page_from_source()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.handover.handover_no} / Line {self.line_no}'


class TenantTruckMovementLog(models.Model):
    """Truck movement log header transaction."""

    class Status(models.TextChoices):
        SCHEDULED = 'Scheduled', 'Scheduled'
        IN_PROGRESS = 'In Progress', 'In Progress'
        COMPLETED = 'Completed', 'Completed'
        CANCELLED = 'Cancelled', 'Cancelled'

    movement_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    movement_no = models.CharField(max_length=64, unique=True)
    movement_sequence = models.PositiveIntegerField(default=0)
    movement_date = models.DateField(default=date.today)
    movement_source = models.CharField(max_length=32, blank=True, default='')
    empty_move_reason = models.CharField(max_length=64, blank=True, default='')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    notes = models.TextField(blank=True, default='')
    booking = models.ForeignKey(
        'TenantBooking',
        on_delete=models.SET_NULL,
        related_name='truck_movements',
        null=True,
        blank=True,
    )
    shipment = models.ForeignKey(
        'TenantShipment',
        on_delete=models.PROTECT,
        related_name='truck_movements',
        null=True,
        blank=True,
    )
    truck = models.ForeignKey(
        'TruckMaster',
        on_delete=models.PROTECT,
        related_name='truck_movements',
        null=True,
        blank=True,
    )
    driver = models.ForeignKey(
        'DriverMaster',
        on_delete=models.PROTECT,
        related_name='truck_movements',
        null=True,
        blank=True,
    )
    from_location_point = models.ForeignKey(
        'TenantLocationMaster',
        on_delete=models.SET_NULL,
        related_name='movements_from',
        null=True,
        blank=True,
    )
    to_location_point = models.ForeignKey(
        'TenantLocationMaster',
        on_delete=models.SET_NULL,
        related_name='movements_to',
        null=True,
        blank=True,
    )
    from_location_map_link = models.URLField(blank=True, default='')
    to_location_map_link = models.URLField(blank=True, default='')
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_truck_movement_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['movement_no'], name='tenant_tml_no_idx'),
            models.Index(fields=['status'], name='tenant_tml_status_idx'),
            models.Index(fields=['booking'], name='tenant_tml_booking_idx'),
            models.Index(fields=['shipment'], name='tenant_tml_shipment_idx'),
            models.Index(fields=['truck'], name='tenant_tml_truck_idx'),
            models.Index(fields=['driver'], name='tenant_tml_driver_idx'),
            models.Index(
                fields=['driver', 'status'],
                name='tenant_tml_driver_status_idx',
            ),
            models.Index(
                fields=['driver', '-updated_at'],
                name='tenant_tml_driver_upd_idx',
            ),
            models.Index(
                fields=['driver', 'status', '-updated_at'],
                name='tenant_tml_drv_stat_upd_idx',
            ),
            models.Index(
                fields=['driver', 'movement_no'],
                name='tenant_tml_drv_mno_idx',
            ),
            models.Index(
                fields=['driver', 'movement_source'],
                name='tenant_tml_drv_src_idx',
            ),
            models.Index(
                fields=['shipment', 'status', '-updated_at'],
                name='tenant_tml_ship_stat_upd_idx',
            ),
        ]

    def __str__(self):
        return self.movement_no


class TenantOperationAction(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    action_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action_code = models.CharField(max_length=64, unique=True)
    arabic_label = models.CharField(max_length=200, blank=True, default='')
    english_label = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    action_scope = models.CharField(max_length=32, blank=True, default='')
    sequence_category = models.CharField(max_length=64, blank=True, default='')
    sequence_number = models.PositiveIntegerField(default=1)
    auto_movement_post = models.BooleanField(default=False)
    auto_shipment_post = models.BooleanField(default=False)
    auto_pod_post = models.BooleanField(default=False)
    auto_treasury_post = models.BooleanField(default=False)
    hard_copy_collection = models.BooleanField(default=False)
    mobile_visible = models.BooleanField(default=False)
    admin_only = models.BooleanField(default=False)
    prerequisite_action_codes = models.CharField(max_length=255, blank=True, default='')
    condition_code = models.CharField(max_length=128, blank=True, default='')
    booking_status_impact = models.CharField(max_length=64, blank=True, default='')
    shipment_status_impact = models.CharField(max_length=64, blank=True, default='')
    movement_status_impact = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_operation_actions'
        ordering = ['action_code']
        indexes = [
            models.Index(fields=['action_code'], name='tenant_op_action_code_idx'),
            models.Index(fields=['status'], name='tenant_op_action_status_idx'),
            models.Index(
                fields=['status', 'action_scope'],
                name='tenant_op_act_stat_scope_idx',
            ),
            models.Index(
                fields=['status', 'sequence_category'],
                name='tenant_op_act_stat_cat_idx',
            ),
            models.Index(
                fields=['status', 'mobile_visible'],
                name='tenant_op_act_mobile_idx',
            ),
            models.Index(
                fields=['status', 'admin_only'],
                name='tenant_op_act_admin_idx',
            ),
        ]

    def __str__(self):
        return self.action_code


class TenantOperationActionLog(models.Model):
    """Operation action log transaction (distinct from truck movement log)."""

    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    log_no = models.CharField(max_length=64, unique=True)
    idempotency_key = models.CharField(max_length=128, blank=True, null=True, unique=True)
    log_sequence = models.PositiveIntegerField(default=0)
    log_date = models.DateTimeField()
    operation_action = models.ForeignKey(
        'TenantOperationAction',
        on_delete=models.SET_NULL,
        related_name='action_logs',
        null=True,
        blank=True,
    )
    source = models.CharField(max_length=32, blank=True, default='Manual')
    source_channel = models.CharField(max_length=32, blank=True, default='admin_manual')
    source_ref = models.CharField(max_length=128, blank=True, default='')
    created_by = models.ForeignKey(
        'TenantUser',
        on_delete=models.SET_NULL,
        related_name='operation_action_logs_created',
        null=True,
        blank=True,
    )
    created_by_label = models.CharField(max_length=200, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    booking = models.ForeignKey(
        'TenantBooking',
        on_delete=models.SET_NULL,
        related_name='operation_action_logs',
        null=True,
        blank=True,
    )
    shipment = models.ForeignKey(
        'TenantShipment',
        on_delete=models.SET_NULL,
        related_name='operation_action_logs',
        null=True,
        blank=True,
    )
    truck_movement = models.ForeignKey(
        'TenantTruckMovementLog',
        on_delete=models.SET_NULL,
        related_name='operation_action_logs',
        null=True,
        blank=True,
    )
    truck = models.ForeignKey(
        'TruckMaster',
        on_delete=models.SET_NULL,
        related_name='operation_action_logs',
        null=True,
        blank=True,
    )
    driver = models.ForeignKey(
        'DriverMaster',
        on_delete=models.SET_NULL,
        related_name='operation_action_logs',
        null=True,
        blank=True,
    )
    latitude = models.CharField(max_length=32, blank=True, default='')
    longitude = models.CharField(max_length=32, blank=True, default='')
    map_link = models.URLField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_operation_action_logs'
        ordering = ['-log_date', '-created_at']
        indexes = [
            models.Index(fields=['log_no'], name='tenant_oal_no_idx'),
            models.Index(fields=['log_date'], name='tenant_oal_date_idx'),
            models.Index(fields=['source'], name='tenant_oal_source_idx'),
            models.Index(fields=['source_channel'], name='tenant_oal_channel_idx'),
            models.Index(fields=['source_ref'], name='tenant_oal_source_ref_idx'),
            models.Index(fields=['booking'], name='tenant_oal_booking_idx'),
            models.Index(fields=['shipment'], name='tenant_oal_shipment_idx'),
            models.Index(fields=['truck_movement'], name='tenant_oal_movement_idx'),
            models.Index(
                fields=['shipment', 'driver', '-log_date'],
                name='tenant_oal_ship_drv_date_idx',
            ),
            models.Index(
                fields=['truck_movement', 'driver', '-log_date'],
                name='tenant_oal_move_drv_date_idx',
            ),
            models.Index(
                fields=['driver', '-log_date'],
                name='tenant_oal_driver_date_idx',
            ),
            models.Index(
                fields=['shipment', 'driver', '-log_date', '-log_id'],
                name='tenant_oal_ship_drv_dt_id_idx',
            ),
            models.Index(
                fields=['truck_movement', 'driver', '-log_date', '-log_id'],
                name='tenant_oal_move_drv_dt_id_idx',
            ),
            models.Index(
                fields=['shipment', '-created_at'],
                name='tenant_oal_ship_created_idx',
            ),
            models.Index(
                fields=['truck_movement', '-created_at'],
                name='tenant_oal_move_created_idx',
            ),
        ]

    def __str__(self):
        return self.log_no


class TenantOperationActionMedia(models.Model):
    """Media evidence rows linked to an operation action log."""

    media_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action_log = models.ForeignKey(
        'TenantOperationActionLog',
        on_delete=models.CASCADE,
        related_name='media_rows',
    )
    line_no = models.PositiveIntegerField(default=1)
    media_type = models.CharField(max_length=16, blank=True, default='')
    captured_at = models.DateTimeField(null=True, blank=True)
    description = models.CharField(max_length=255, blank=True, default='')
    file = models.FileField(
        upload_to=operation_action_media_upload_to,
        blank=True,
        default='',
        max_length=500,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tenant_operation_action_media'
        ordering = ['line_no', 'created_at']
        indexes = [
            models.Index(fields=['action_log'], name='tenant_oal_media_log_idx'),
        ]

    def __str__(self):
        return f'{self.action_log_id}:{self.line_no}'


class DriverMobileNotification(models.Model):
    """
    Tenant-scoped driver inbox row for mobile dashboard / FCM follow-up.

    Phase 1: populated by operational sync + future push ingest; dashboard
    returns summary projections only (not full inbox history).
    """

    class Category(models.TextChoices):
        GENERAL = 'general', 'General'
        CRITICAL = 'critical', 'Critical'
        ASSIGNMENT = 'assignment', 'Assignment'
        OPERATIONAL_WARNING = 'operational_warning', 'Operational Warning'

    class Severity(models.TextChoices):
        INFO = 'info', 'Info'
        WARNING = 'warning', 'Warning'
        CRITICAL = 'critical', 'Critical'

    class Source(models.TextChoices):
        SYSTEM = 'system', 'System'
        OPERATIONAL = 'operational', 'Operational'
        PUSH = 'push', 'Push'
        FCM = 'fcm', 'FCM'

    notification_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    driver = models.ForeignKey(
        'DriverMaster',
        on_delete=models.CASCADE,
        related_name='mobile_notifications',
    )
    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.GENERAL,
    )
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.INFO,
    )
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.SYSTEM,
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default='')
    event_code = models.CharField(max_length=64, blank=True, default='')
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    shipment_id = models.UUIDField(null=True, blank=True)
    movement_id = models.UUIDField(null=True, blank=True)
    fcm_message_id = models.CharField(max_length=128, blank=True, default='')
    push_receipt_id = models.UUIDField(
        null=True,
        blank=True,
        help_text='Optional link to public ``PushNotificationReceipt``.',
    )
    dedupe_key = models.CharField(
        max_length=128,
        blank=True,
        default='',
        db_index=True,
        help_text='Idempotent upsert key for operational/FCM ingest.',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_driver_mobile_notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['driver', 'is_read', '-created_at'],
                name='tenant_drv_notif_unread_idx',
            ),
            models.Index(
                fields=['driver', 'category', 'is_read'],
                name='tenant_drv_notif_cat_idx',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['driver', 'dedupe_key'],
                condition=~models.Q(dedupe_key=''),
                name='tenant_drv_notif_dedupe_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.driver_id} :: {self.category} :: {self.title[:40]}'


