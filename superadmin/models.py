from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from decimal import Decimal
import uuid


class AdminUserManager(BaseUserManager):
    def create_superuser(self, email, password):
        user = self.model(email=email, status='Active', is_root=True)
        user.set_password(password)
        user.save(using=self._db)
        return user


class Role(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    ]

    role_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role_name_en = models.CharField(max_length=50, unique=True)
    role_name_ar = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    is_system_default = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='Active'
    )
    created_by = models.ForeignKey(
        'AdminUser',
        on_delete=models.SET_NULL,
        null=True,
        related_name='roles_created',
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        on_delete=models.SET_NULL,
        null=True,
        related_name='roles_updated',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.role_name_en

    class Meta:
        verbose_name = 'Role'
        verbose_name_plural = 'Roles'
        db_table = 'superadmin_roles'
        ordering = ['role_name_en']


class AdminUser(AbstractBaseUser):
    STATUS_CHOICES = [
        ('Pending_Activation', 'Pending Activation'),
        ('Active', 'Active'),
        ('Suspended', 'Suspended'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField(max_length=100, unique=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='Pending_Activation'
    )
    is_deleted = models.BooleanField(default=False)
    role = models.ForeignKey(
        'Role', on_delete=models.SET_NULL, null=True, blank=True, related_name='admin_users'
    )
    is_root = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)
    last_login_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        'AdminUser',
        on_delete=models.SET_NULL,
        null=True,
        related_name='admins_created',
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        on_delete=models.SET_NULL,
        null=True,
        related_name='admins_updated',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    objects = AdminUserManager()

    class Meta:
        verbose_name = 'Admin User'
        verbose_name_plural = 'Admin Users'
        db_table = 'superadmin_users'

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

    @property
    def is_active(self):
        return self.status == 'Active'

    @property
    def is_staff(self):
        return self.is_root

    @property
    def is_superuser(self):
        return self.is_root

    def has_perm(self, perm, obj=None):
        return self.is_root

    def has_module_perms(self, app_label):
        return self.is_root


class AdminSecuritySettings(models.Model):
    """PCS FRM-CP-11-01 — single-row admin security configuration."""

    setting_id = models.CharField(
        primary_key=True,
        max_length=50,
        default='ADMIN-SEC-CONF',
    )
    session_timeout_minutes = models.IntegerField(default=1440)
    max_failed_logins = models.IntegerField(default=3)
    lockout_duration_minutes = models.IntegerField(default=30)
    otp_timeout_seconds = models.IntegerField(default=240)
    updated_by = models.ForeignKey(
        'AdminUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_settings_updated',
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return 'Admin Security Settings'

    class Meta:
        db_table = 'superadmin_security_settings'
        verbose_name = 'Admin Security Settings'


class TenantSecuritySettings(models.Model):
    setting_id = models.CharField(
        primary_key=True,
        max_length=50,
        default='TENANT-SEC-CONF',
    )
    tenant_web_timeout_hours = models.IntegerField(
        default=12,
        validators=[MinValueValidator(1)],
    )
    driver_app_timeout_days = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1)],
    )
    max_failed_logins = models.IntegerField(
        default=5,
        validators=[MinValueValidator(1)],
    )
    lockout_duration_minutes = models.IntegerField(
        default=15,
        validators=[MinValueValidator(1)],
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return 'Tenant Security Settings'

    class Meta:
        db_table = 'security_tenant_settings'


class ActiveSession(models.Model):
    DOMAIN_CHOICES = [
        ('Admin', 'Admin'),
        ('Tenant_User', 'Tenant User'),
        ('Driver', 'Driver'),
    ]

    # TODO Phase 11 Redis: Replace DB-based session
    # tracking with Redis cache for real-time JWT
    # revocation when Redis is implemented.
    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user_domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES)
    reference_id = models.CharField(
        max_length=100,
        help_text='User or Driver ID',
    )
    reference_name = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text='Display name for UI',
    )
    tenant = models.ForeignKey(
        'TenantProfile',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='active_sessions',
    )
    redis_jti = models.CharField(
        max_length=128,
        blank=True,
        default='',
        db_index=True,
        help_text='Redis JTI for CP Kill Switch / mass revoke.',
    )
    ip_address = models.CharField(max_length=45)
    user_agent = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        'AdminUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='revoked_sessions',
    )

    def __str__(self):
        return f'{self.user_domain} - {self.reference_name or self.reference_id}'

    class Meta:
        db_table = 'security_active_sessions'
        ordering = ['-started_at']


class AuditLogQuerySet(models.QuerySet):
    def delete(self):
        raise PermissionError(
            'Audit log entries cannot be bulk-deleted.',
        )

    def update(self, **kwargs):
        raise PermissionError(
            'Audit log entries cannot be bulk-updated.',
        )


class AuditLogManager(models.Manager):
    def get_queryset(self):
        return AuditLogQuerySet(self.model, using=self._db)


class AuditLog(models.Model):
    ACTION_TYPE_CHOICES = [
        ('Create', 'Create'),
        ('Update', 'Update'),
        ('Delete', 'Delete'),
        ('Status_Change', 'Status Change'),
    ]

    objects = AuditLogManager()

    audit_id = models.AutoField(primary_key=True)
    admin = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
    )
    action_type = models.CharField(max_length=20, choices=ACTION_TYPE_CHOICES)
    module_name = models.CharField(
        max_length=100,
        help_text='e.g. Tax Settings, Subscription Plans',
    )
    record_id = models.CharField(
        max_length=100,
        help_text='ID of the modified entity',
    )
    old_payload = models.JSONField(
        null=True,
        blank=True,
        help_text='State before update. Null on Create.',
    )
    new_payload = models.JSONField(
        null=True,
        blank=True,
        help_text='State after update. Null on Delete.',
    )
    ip_address = models.CharField(max_length=45)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return (
            f'{self.action_type} on '
            f'{self.module_name} by '
            f'{self.admin}'
        )

    class Meta:
        db_table = 'security_audit_log'
        ordering = ['-timestamp']

    def save(self, *args, **kwargs):
        if self.pk and AuditLog.objects.filter(
                audit_id=self.audit_id).exists():
            raise PermissionError(
                'Audit log entries are immutable.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(
            'Audit log entries cannot be deleted.'
        )


class AdminAuthToken(models.Model):
    """Invite and password reset tokens for admin users."""

    class TokenType(models.TextChoices):
        INVITE = 'invite', 'invite'
        PASSWORD_RESET = 'password_reset', 'password_reset'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin_user = models.ForeignKey(
        'AdminUser',
        on_delete=models.CASCADE,
        related_name='auth_tokens',
    )
    token = models.CharField(max_length=100, unique=True)
    token_type = models.CharField(
        max_length=20,
        choices=TokenType.choices,
    )
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    @property
    def is_expired(self):
        from django.utils import timezone

        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired

    def __str__(self):
        return f"{self.token_type} token for {self.admin_user.email}"

    class Meta:
        db_table = 'superadmin_auth_tokens'


class LoginAttempt(models.Model):
    """Brute-force tracking per email (email is not an FK)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    failed_count = models.IntegerField(default=0)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'LoginAttempt for {self.email}'

    class Meta:
        db_table = 'superadmin_login_attempts'


class AccessLog(models.Model):
    """Append-only access log for auth events."""

    class AttemptType(models.TextChoices):
        LOGIN = 'Login', 'Login'
        LOGOUT = 'Logout', 'Logout'
        TOKEN_REFRESH = 'Token_Refresh', 'Token_Refresh'

    class Status(models.TextChoices):
        SUCCESS = 'Success', 'Success'
        FAILED = 'Failed', 'Failed'
        BLOCKED = 'Blocked', 'Blocked'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt_type = models.CharField(max_length=20, choices=AttemptType.choices)
    status = models.CharField(max_length=20, choices=Status.choices)
    user_domain = models.CharField(max_length=50, default='Admin')
    email_used = models.EmailField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError(
                'Access logs are immutable and cannot be modified.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Access logs cannot be deleted.')

    def __str__(self):
        return f"{self.attempt_type} - {self.email_used} - {self.status}"

    class Meta:
        db_table = 'superadmin_access_logs'
        ordering = ['-timestamp']


class Country(models.Model):
    """PCS FRM-CP-08-01 — Countries master data."""

    country_code = models.CharField(
        primary_key=True,
        max_length=10,
        help_text='ISO Country Code e.g. SA, US, AE',
    )
    name_en = models.CharField(max_length=100, unique=True)
    name_ar = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='countries_created',
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name_en} ({self.country_code})"

    class Meta:
        db_table = 'master_countries'
        verbose_name = 'Country'
        verbose_name_plural = 'Countries'
        ordering = ['name_en']


class Currency(models.Model):
    """PCS FRM-CP-08-02 — Currencies master data."""

    currency_code = models.CharField(
        primary_key=True,
        max_length=10,
        help_text='ISO Currency Code e.g. SAR, USD',
    )
    name_en = models.CharField(max_length=100)
    name_ar = models.CharField(max_length=100)
    currency_symbol = models.CharField(max_length=10)
    decimal_places = models.IntegerField(default=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='currencies_created',
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name_en} ({self.currency_code})"

    class Meta:
        db_table = 'master_currencies'
        verbose_name = 'Currency'
        verbose_name_plural = 'Currencies'
        ordering = ['name_en']


class TaxCode(models.Model):
    tax_code = models.CharField(primary_key=True, max_length=20)
    name_en = models.CharField(max_length=100)
    name_ar = models.CharField(max_length=100)
    rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    applicable_country_code = models.ForeignKey(
        Country,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tax_codes',
    )
    is_default_for_country = models.BooleanField(default=False)
    is_international_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
        related_name='tax_codes_created',
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tax_codes_updated',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name_en} ({self.tax_code})"

    class Meta:
        db_table = 'config_tax_codes'
        ordering = ['tax_code']


class GeneralTaxSettings(models.Model):
    LOCATION_CHOICES = [
        ('Profile_Only', 'Profile Only'),
        ('Audit_Only', 'Audit Only'),
        ('Enforce_Profile_Match', 'Enforce Profile Match'),
    ]

    setting_id = models.CharField(
        primary_key=True,
        max_length=50,
        default='GLOBAL-TAX-SETTING',
    )
    prices_include_tax = models.BooleanField(default=False)
    location_verification = models.CharField(
        max_length=30,
        choices=LOCATION_CHOICES,
        default='Profile_Only',
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return 'General Tax Settings'

    class Meta:
        db_table = 'config_general_tax_settings'


class LegalIdentity(models.Model):
    identity_id = models.CharField(
        primary_key=True,
        max_length=50,
        default='GLOBAL-LEGAL-IDENTITY',
    )
    company_logo = models.ImageField(
        upload_to='legal/',
        null=True,
        blank=True,
    )
    company_name_en = models.CharField(max_length=100)
    company_name_ar = models.CharField(max_length=100)
    company_country_code = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    commercial_register = models.CharField(max_length=50)
    tax_number = models.CharField(max_length=50)
    registered_address = models.TextField()
    support_email = models.EmailField(max_length=100)
    support_phone = models.CharField(max_length=20, null=True, blank=True)
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return 'IRoad Legal Identity'

    class Meta:
        db_table = 'config_legal_identity'


class GlobalSystemRules(models.Model):
    DATE_FORMAT_CHOICES = [
        ('YYYY-MM-DD', 'YYYY-MM-DD'),
        ('DD/MM/YYYY', 'DD/MM/YYYY'),
    ]

    rule_id = models.CharField(
        primary_key=True,
        max_length=50,
        default='GLOBAL-SYSTEM-RULES',
    )
    system_timezone = models.CharField(max_length=100, default='Asia/Riyadh')
    default_date_format = models.CharField(
        max_length=20,
        choices=DATE_FORMAT_CHOICES,
        default='DD/MM/YYYY',
    )
    grace_period_days = models.IntegerField(
        default=3,
        validators=[MinValueValidator(0)],
    )
    standard_billing_cycle = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1)],
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return 'Global System Rules'

    class Meta:
        db_table = 'config_system_rules'


class BaseCurrencyConfig(models.Model):
    setting_id = models.CharField(
        primary_key=True,
        max_length=50,
        default='GLOBAL-BASE-CURRENCY',
    )
    base_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='base_currency_config',
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Base Currency: {self.base_currency_id}"

    class Meta:
        db_table = 'config_base_currency'


class ExchangeRate(models.Model):
    fx_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name='exchange_rates',
    )
    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))],
    )
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.currency_id} = {self.exchange_rate}"

    class Meta:
        db_table = 'config_exchange_rates'


class FXRateChangeLog(models.Model):
    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name='fx_change_logs',
    )
    old_rate = models.DecimalField(max_digits=10, decimal_places=6)
    new_rate = models.DecimalField(max_digits=10, decimal_places=6)
    notes = models.TextField(null=True, blank=True)
    changed_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.currency_id}: {self.old_rate} → {self.new_rate}"

    class Meta:
        db_table = 'config_fx_change_log'
        ordering = ['-changed_at']

    def save(self, *args, **kwargs):
        if self.pk and FXRateChangeLog.objects.filter(
            log_id=self.log_id
        ).exists():
            raise PermissionError(
                'FX Rate Change Log entries are immutable.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(
            'FX Rate Change Log entries cannot be deleted.'
        )


class SubscriptionPlan(models.Model):
    BACKUP_LEVEL_CHOICES = [
        ('Standard', 'Standard'),
        ('Extended', 'Extended'),
        ('Premium', 'Premium'),
    ]

    plan_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    plan_name_en = models.CharField(max_length=50, unique=True)
    plan_name_ar = models.CharField(max_length=50, unique=True)
    base_cycle_days = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1)],
    )
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    max_internal_users = models.IntegerField(
        default=-1,
        help_text='-1 means Unlimited',
    )
    max_internal_trucks = models.IntegerField(default=-1)
    max_external_trucks = models.IntegerField(default=-1)
    max_active_drivers = models.IntegerField(default=-1)
    max_monthly_shipments = models.IntegerField(default=-1)
    max_storage_gb = models.IntegerField(default=-1)
    has_driver_app = models.BooleanField(default=False)
    backup_restore_level = models.CharField(
        max_length=20,
        choices=BACKUP_LEVEL_CHOICES,
        default='Standard',
    )
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
        related_name='plans_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.plan_name_en

    class Meta:
        db_table = 'subscription_plans'
        ordering = ['plan_name_en']


class PlanPricingCycle(models.Model):
    pricing_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.CASCADE,
        related_name='pricing_cycles',
    )
    number_of_cycles = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name='plan_pricing',
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )

    def __str__(self):
        return (
            f"{self.plan.plan_name_en} - "
            f"{self.number_of_cycles} cycle(s) - "
            f"{self.currency_id}"
        )

    class Meta:
        db_table = 'subscription_plan_pricing'
        unique_together = [['plan', 'number_of_cycles', 'currency']]
        ordering = ['number_of_cycles']


class AddOnsPricingPolicy(models.Model):
    policy_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    policy_name = models.CharField(max_length=50)
    is_active = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    extra_internal_user_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    extra_internal_truck_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    extra_external_truck_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    extra_driver_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    extra_shipment_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    extra_storage_gb_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.policy_name

    class Meta:
        db_table = 'subscription_addons_policy'
        ordering = ['-updated_at']


class PromoCode(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ('Percentage', 'Percentage'),
        ('Fixed_Amount', 'Fixed Amount'),
    ]
    DURATION_CHOICES = [
        ('Apply_Once', 'Apply Once'),
        ('Recurring', 'Recurring'),
    ]

    promo_code_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    code = models.CharField(max_length=20, unique=True)
    discount_type = models.CharField(
        max_length=20,
        choices=DISCOUNT_TYPE_CHOICES,
        default='Percentage',
    )
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    discount_duration = models.CharField(
        max_length=20,
        choices=DURATION_CHOICES,
        default='Apply_Once',
    )
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    max_uses = models.IntegerField(null=True, blank=True)
    current_uses = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    applicable_plans = models.ManyToManyField(
        SubscriptionPlan,
        blank=True,
        related_name='promo_codes',
    )
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.code

    class Meta:
        db_table = 'subscription_promo_codes'
        ordering = ['-created_at']

    def is_valid_for_use(self, for_plan=None):
        """
        Order validation order: is_active → valid_from/until →
        max_uses vs current_uses → applicable_plans (when restricted).
        Returns (ok, message). On failure, message is the generic
        client-facing error for apply-to-order flows.
        """
        from django.utils import timezone

        invalid_msg = 'Invalid or Expired Code'

        if not self.is_active:
            return False, invalid_msg
        now = timezone.now()
        if now < self.valid_from:
            return False, invalid_msg
        if self.valid_until and now > self.valid_until:
            return False, invalid_msg
        if self.max_uses is not None and self.current_uses >= self.max_uses:
            # Keep status aligned with usage cap once exhausted.
            if self.is_active:
                self.is_active = False
                self.save(update_fields=['is_active'])
            return False, invalid_msg

        plan_qs = self.applicable_plans.all()
        if plan_qs.exists():
            if for_plan is None:
                return False, invalid_msg
            if not plan_qs.filter(pk=for_plan.pk).exists():
                return False, invalid_msg

        return True, ''


class BankAccount(models.Model):
    account_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    bank_name = models.CharField(max_length=100)
    account_holder_name = models.CharField(max_length=100)
    iban_number = models.CharField(
        max_length=34,
        help_text='IBAN format: e.g. SA0380000000608010167519',
    )
    account_number = models.CharField(max_length=30)
    swift_code = models.CharField(max_length=11, null=True, blank=True)
    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name='bank_accounts',
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
        related_name='bank_accounts_created',
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='bank_accounts_updated',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.bank_name} - "
            f"{self.currency_id} - {self.iban_number[-4:]}"
        )

    class Meta:
        db_table = 'payment_bank_accounts'
        ordering = ['bank_name']


class PaymentGateway(models.Model):
    ENVIRONMENT_CHOICES = [
        ('Test', 'Test'),
        ('Live', 'Live'),
    ]

    gateway_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    gateway_name = models.CharField(max_length=50)
    environment = models.CharField(
        max_length=10,
        choices=ENVIRONMENT_CHOICES,
        default='Test',
    )
    credentials_payload = models.JSONField(
        help_text='JSON object with gateway credentials'
    )
    is_active = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
        related_name='gateways_created',
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='gateways_updated',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.gateway_name} ({self.environment})"

    class Meta:
        db_table = 'payment_gateways'
        ordering = ['gateway_name']


class PaymentMethod(models.Model):
    METHOD_TYPE_CHOICES = [
        ('Online_Gateway', 'Online Gateway'),
        ('Offline_Bank', 'Offline Bank Transfer'),
    ]

    method_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    method_name_en = models.CharField(max_length=100)
    method_name_ar = models.CharField(max_length=100)
    method_type = models.CharField(
        max_length=20,
        choices=METHOD_TYPE_CHOICES,
    )
    supported_currencies = models.JSONField(
        default=list,
        help_text='Array of currency codes e.g. ["SAR","USD"]',
    )
    gateway = models.ForeignKey(
        PaymentGateway,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='payment_methods',
    )
    dedicated_bank_account = models.ForeignKey(
        BankAccount,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='payment_methods',
    )
    logo = models.ImageField(
        upload_to='payment_methods/',
        null=True,
        blank=True,
    )
    display_order = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
        related_name='payment_methods_created',
    )
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='payment_methods_updated',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.method_name_en

    class Meta:
        db_table = 'payment_methods'
        ordering = ['display_order']


class CommGateway(models.Model):
    GATEWAY_TYPE_CHOICES = [
        ('Email', 'Email (SMTP)'),
        ('SMS', 'SMS API'),
    ]
    ENCRYPTION_CHOICES = [
        ('TLS', 'TLS'),
        ('SSL', 'SSL'),
        ('None', 'None'),
    ]

    gateway_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    gateway_type = models.CharField(max_length=10, choices=GATEWAY_TYPE_CHOICES)
    provider_name = models.CharField(max_length=100)
    host_url = models.CharField(max_length=255)
    port = models.IntegerField(null=True, blank=True)
    username_key = models.CharField(max_length=255)
    password_secret = models.CharField(
        max_length=255,
        help_text='Stored securely. Never displayed after save.',
    )
    sender_id = models.CharField(
        max_length=100,
        help_text='From email address or SMS sender name',
    )
    encryption_type = models.CharField(
        max_length=10,
        choices=ENCRYPTION_CHOICES,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider_name} ({self.gateway_type})"

    def save(self, *args, **kwargs):
        """Spec CP-PCS-P6 §5.1.3: The system can store multiple gateways,
        but only ONE gateway per gateway_type can have is_active = True.
        """
        if self.is_active:
            # Atomic update of others of same type to False
            CommGateway.objects.filter(
                gateway_type=self.gateway_type
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'comm_gateways'
        ordering = ['gateway_type']


class NotificationTemplate(models.Model):
    CHANNEL_CHOICES = [
        ('Email', 'Email'),
        ('SMS', 'SMS'),
    ]
    CATEGORY_CHOICES = [
        ('Transactional', 'Transactional'),
        ('Promotional', 'Promotional'),
    ]

    template_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    template_name = models.CharField(max_length=100, unique=True)
    channel_type = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    subject_en = models.CharField(max_length=255, null=True, blank=True)
    subject_ar = models.CharField(max_length=255, null=True, blank=True)
    body_en = models.TextField()
    body_ar = models.TextField()
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.template_name} ({self.channel_type})"

    class Meta:
        db_table = 'comm_templates'
        ordering = ['template_name']


class EventMapping(models.Model):
    SYSTEM_EVENT_CHOICES = [
        ('OTP_Requested', 'OTP Requested'),
        ('Password_Changed', 'Password Changed'),
        ('Invoice_Paid', 'Invoice Paid'),
        ('Subscription_Activated', 'Subscription Activated'),
        ('Subscription_Expired', 'Subscription Expired'),
        ('Subscription_Renewed', 'Subscription Renewed'),
        ('Account_Suspended', 'Account Suspended'),
        ('Welcome_Email', 'Welcome Email'),
        ('Password_Reset_Requested', 'Password Reset Requested'),
        ('Payment_Failed', 'Payment Failed'),
        ('Support_Ticket_Created', 'Support Ticket Created'),
        ('Support_Ticket_Replied', 'Support Ticket Replied'),
    ]
    CHANNEL_CHOICES = [
        ('Email', 'Email'),
        ('SMS', 'SMS'),
    ]

    mapping_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    system_event = models.CharField(
        max_length=50,
        choices=SYSTEM_EVENT_CHOICES,
        unique=True,
    )
    primary_channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    primary_template = models.ForeignKey(
        NotificationTemplate,
        on_delete=models.PROTECT,
        related_name='primary_mappings',
    )
    fallback_channel = models.CharField(
        max_length=10,
        choices=CHANNEL_CHOICES,
        null=True,
        blank=True,
    )
    fallback_template = models.ForeignKey(
        NotificationTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='fallback_mappings',
    )
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_system_event_display()} → {self.primary_channel}"

    class Meta:
        db_table = 'comm_event_mappings'
        ordering = ['system_event']


class PushNotification(models.Model):
    TRIGGER_MODE_CHOICES = [
        ('Manual_Broadcast', 'Manual Broadcast'),
        ('System_Event', 'System Event'),
    ]
    AUDIENCE_CHOICES = [
        ('All', 'All Users'),
        ('Tenants', 'Tenants Only'),
        ('Drivers', 'Drivers Only'),
        ('Specific', 'Specific Target'),
    ]
    DISPATCH_STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Scheduled', 'Scheduled'),
        ('Completed', 'Completed'),
    ]

    notification_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    internal_name = models.CharField(max_length=100)
    title_en = models.CharField(max_length=255)
    title_ar = models.CharField(max_length=255)
    message_en = models.TextField()
    message_ar = models.TextField()
    action_link = models.URLField(null=True, blank=True)
    trigger_mode = models.CharField(max_length=20, choices=TRIGGER_MODE_CHOICES)
    linked_event = models.CharField(
        max_length=50,
        choices=EventMapping.SYSTEM_EVENT_CHOICES,
        null=True,
        blank=True,
    )
    target_audience = models.CharField(
        max_length=20,
        choices=AUDIENCE_CHOICES,
        null=True,
        blank=True,
    )
    specific_target_id = models.CharField(max_length=100, null=True, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    dispatch_status = models.CharField(
        max_length=20,
        choices=DISPATCH_STATUS_CHOICES,
        default='Draft',
    )
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.internal_name

    class Meta:
        db_table = 'comm_push_notifications'
        ordering = ['-created_at']


class PushDeviceToken(models.Model):
    DOMAIN_CHOICES = [
        ('Tenant_User', 'Tenant User'),
        ('Driver', 'Driver'),
        ('Admin', 'Admin'),
    ]

    token_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    tenant = models.ForeignKey(
        'TenantProfile',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='push_device_tokens',
    )
    user_domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES)
    reference_id = models.CharField(
        max_length=100,
        help_text='Domain entity ID, e.g. tenant user ID or driver ID',
    )
    device_token = models.CharField(max_length=512, unique=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user_domain} - {self.reference_id}'

    class Meta:
        db_table = 'comm_push_device_tokens'
        ordering = ['-updated_at']


class PushNotificationReceipt(models.Model):
    STATUS_CHOICES = [
        ('Sent', 'Sent'),
        ('Failed', 'Failed'),
    ]

    receipt_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    tenant = models.ForeignKey(
        'TenantProfile',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='push_receipts',
    )
    notification = models.ForeignKey(
        PushNotification,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='receipts',
    )
    device_token = models.CharField(max_length=512)
    user_domain = models.CharField(max_length=20, choices=PushDeviceToken.DOMAIN_CHOICES)
    reference_id = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    message = models.TextField()
    action_link = models.URLField(null=True, blank=True)
    event_code = models.CharField(max_length=50, null=True, blank=True)
    delivery_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Sent')
    error_details = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'comm_push_receipts'
        ordering = ['-created_at']


class SystemBanner(models.Model):
    SEVERITY_CHOICES = [
        ('Info', 'Info (Blue)'),
        ('Warning', 'Warning (Yellow)'),
        ('Critical', 'Critical (Red)'),
    ]

    banner_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    title_en = models.CharField(max_length=255)
    title_ar = models.CharField(max_length=255)
    message_en = models.TextField()
    message_ar = models.TextField()
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default='Info',
    )
    is_dismissible = models.BooleanField(default=True)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title_en} ({self.severity})"

    @property
    def is_expired(self):
        from django.utils import timezone
        if self.valid_until:
            return timezone.now() > self.valid_until
        return False

    class Meta:
        db_table = 'comm_system_banners'
        ordering = ['-valid_from']


class InternalAlertRoute(models.Model):
    TRIGGER_EVENT_CHOICES = [
        ('New_Tenant_Registered', 'New Tenant Registered'),
        ('High_Priority_Ticket', 'High Priority Ticket'),
        ('Payment_Failed', 'Payment Failed'),
        ('Subscription_Expired', 'Subscription Expired'),
        ('Bank_Transfer_Pending', 'Bank Transfer Pending'),
        ('System_Error', 'System Error'),
    ]

    route_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    trigger_event = models.CharField(max_length=50, choices=TRIGGER_EVENT_CHOICES)
    notify_role = models.ForeignKey(
        Role,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='alert_routes',
    )
    notify_custom_email = models.EmailField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return (
            f"{self.get_trigger_event_display()} → "
            f"{self.notify_role or self.notify_custom_email}"
        )

    class Meta:
        db_table = 'comm_alert_routes'
        ordering = ['trigger_event']



class InternalAlertNotification(models.Model):
    notification_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    admin_user = models.ForeignKey(
        'AdminUser',
        on_delete=models.CASCADE,
        related_name='internal_alert_notifications',
    )
    route = models.ForeignKey(
        InternalAlertRoute,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='notifications',
    )
    trigger_event = models.CharField(
        max_length=50,
        choices=InternalAlertRoute.TRIGGER_EVENT_CHOICES,
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    context_payload = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'comm_internal_alert_notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.admin_user.email} :: {self.trigger_event}'


class CommLog(models.Model):
    CHANNEL_CHOICES = [
        ('Email', 'Email'),
        ('SMS', 'SMS'),
        ('Push', 'Push Notification'),
    ]
    STATUS_CHOICES = [
        ('Sent', 'Sent'),
        ('Failed', 'Failed'),
        ('Bounced', 'Bounced'),
    ]

    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    recipient = models.CharField(
        max_length=255,
        help_text='Email, phone number, or FCM token',
    )
    client_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text='Tenant reference for filtering',
    )
    channel_type = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    trigger_source = models.CharField(
        max_length=255,
        help_text='e.g. Event: OTP_Requested',
    )
    delivery_status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_details = models.TextField(null=True, blank=True)
    dispatched_at = models.DateTimeField(auto_now_add=True)

    # TODO Phase 11: Implement 90-day log archival/cleanup

    def __str__(self):
        return f"{self.channel_type} to {self.recipient} - {self.delivery_status}"

    def save(self, *args, **kwargs):
        if self.pk and CommLog.objects.filter(log_id=self.log_id).exists():
            raise PermissionError('Communication logs are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Communication logs cannot be deleted.')

    class Meta:
        db_table = 'comm_logs'
        ordering = ['-dispatched_at']


class TenantProfile(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Suspended_Billing', 'Suspended - Billing'),
        ('Suspended_Violation', 'Suspended - Violation'),
        ('Churned', 'Churned'),
    ]

    tenant_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    first_name = models.CharField(max_length=50, blank=True, default='')
    last_name = models.CharField(max_length=50, blank=True, default='')
    company_name = models.CharField(max_length=100)
    registration_number = models.CharField(max_length=50)
    tax_number = models.CharField(max_length=50, null=True, blank=True)
    primary_email = models.EmailField(max_length=100)
    primary_phone = models.CharField(max_length=20)
    country = models.ForeignKey(
        'Country',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='tenant_profiles',
    )
    registered_address = models.TextField(
        blank=True,
        default='',
        help_text='Registered address for tenant profile.',
    )
    account_status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default='Active',
    )
    is_deleted = models.BooleanField(default=False)
    assigned_sales_rep = models.ForeignKey(
        'AdminUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='assigned_tenants',
    )
    wallet_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    api_bridge_secret_hash = models.TextField(
        blank=True,
        default='',
        help_text='Hashed secret for tenant API bridge (/api/v1/). Rotated from Control Panel.',
    )
    portal_bootstrap_password_hash = models.TextField(
        blank=True,
        default='',
        help_text=(
            'Hashed initial tenant-portal password set at provisioning (CP-PCS-P1 '
            'handover). Plaintext sent once in welcome email; not shown in CP.'
        ),
    )
    workspace_schema = models.CharField(
        max_length=63,
        blank=True,
        default='',
        db_index=True,
        help_text='PostgreSQL schema name for isolated tenant workspace (CP 4.3.2).',
    )
  
    registered_at = models.DateTimeField(auto_now_add=True)
    total_ltv = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    current_plan = models.ForeignKey(
        'SubscriptionPlan',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='active_tenants',
    )
    subscription_start_date = models.DateField(null=True, blank=True)
    subscription_expiry_date = models.DateField(null=True, blank=True)
    scheduled_downgrade_plan = models.ForeignKey(
        'SubscriptionPlan',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tenants_pending_downgrade',
    )
    scheduled_downgrade_effective_date = models.DateField(
        null=True,
        blank=True,
        help_text='Date the subscriber moves to the lower plan (end of current cycle).',
    )
    active_max_users = models.IntegerField(default=0)
    active_max_internal_trucks = models.IntegerField(default=0)
    active_max_external_trucks = models.IntegerField(default=0)
    active_max_drivers = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.company_name

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__original_status = self.account_status

    def save(self, *args, **kwargs):
        """Ref: CP-PCS-P1 §5.1 - Centralized Session Kill Switch."""
     

        SUSPEND_STATUSES = ['Suspended_Billing', 'Suspended_Violation']
        is_new_suspension = (
            self.account_status in SUSPEND_STATUSES
            and self.__original_status not in SUSPEND_STATUSES
        )

        super().save(*args, **kwargs)

        if is_new_suspension:
            from superadmin.tasks import revoke_tenant_sessions_task
            revoke_tenant_sessions_task.delay(str(self.tenant_id))

        self.__original_status = self.account_status

    class Meta:
        db_table = 'crm_tenant_profiles'
        ordering = ['company_name']
        constraints = [
            models.UniqueConstraint(
                fields=['workspace_schema'],
                condition=~models.Q(workspace_schema=''),
                name='uniq_tenant_workspace_schema_when_set',
            ),
        ]


class CRMNote(models.Model):
    NOTE_TYPE_CHOICES = [
        ('General', 'General'),
        ('Sales_Call', 'Sales Call'),
        ('Billing_Issue', 'Billing Issue'),
        ('Complaint', 'Complaint'),
    ]

    note_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    tenant = models.ForeignKey(
        TenantProfile,
        on_delete=models.CASCADE,
        related_name='crm_notes',
    )
    admin = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
        related_name='crm_notes',
    )
    note_type = models.CharField(
        max_length=20,
        choices=NOTE_TYPE_CHOICES,
        default='General',
    )
    note_content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.note_type} note for {self.tenant.company_name}'

    def save(self, *args, **kwargs):
        if self.pk and CRMNote.objects.filter(note_id=self.note_id).exists():
            raise PermissionError(
                'CRM Notes are immutable after creation.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('CRM Notes cannot be deleted.')

    class Meta:
        db_table = 'crm_notes'
        ordering = ['-created_at']


class SubscriptionOrder(models.Model):
    CLASSIFICATION_CHOICES = [
        ('New_Subscription', 'New Subscription'),
        ('Renewal', 'Renewal'),
        ('Upgrade', 'Upgrade'),
        ('Downgrade', 'Downgrade'),
        ('Add_ons', 'Add-ons'),
    ]
    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Pending_Payment', 'Pending Payment'),
        ('Paid', 'Paid'),
        ('Cancelled', 'Cancelled'),
    ]

    order_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    tenant = models.ForeignKey(
        TenantProfile,
        on_delete=models.PROTECT,
        related_name='orders',
    )
    order_classification = models.CharField(
        max_length=20,
        choices=CLASSIFICATION_CHOICES,
        default='New_Subscription',
    )
    promo_code = models.ForeignKey(
        'PromoCode',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='orders',
    )
    tax_code = models.ForeignKey(
        'TaxCode',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    currency = models.ForeignKey(
        'Currency',
        on_delete=models.PROTECT,
        related_name='subscription_orders',
    )
    sub_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    grand_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    exchange_rate_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal('1.000000'),
    )
    base_currency_equivalent = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    order_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Draft',
    )
    payment_method = models.ForeignKey(
        'PaymentMethod',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
        related_name='orders_created',
    )
    projected_plan = models.ForeignKey(
        'SubscriptionPlan',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='projected_orders',
    )
    projected_expiry_date = models.DateField(null=True, blank=True)
    projected_max_users = models.IntegerField(null=True, blank=True)
    projected_max_internal_trucks = models.IntegerField(null=True, blank=True)
    projected_max_external_trucks = models.IntegerField(null=True, blank=True)
    projected_max_drivers = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f'Order {self.order_id} - '
            f'{self.tenant.company_name} - '
            f'{self.order_classification}'
        )

    class Meta:
        db_table = 'crm_subscription_orders'
        ordering = ['-created_at']


class OrderPlanLine(models.Model):
    line_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    order = models.ForeignKey(
        SubscriptionOrder,
        on_delete=models.CASCADE,
        related_name='plan_lines',
    )
    plan = models.ForeignKey(
        'SubscriptionPlan',
        on_delete=models.PROTECT,
    )
    number_of_cycles = models.IntegerField(default=1)
    plan_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    pro_rata_adjustment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    line_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    plan_name_en_snapshot = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Plan display name at order time (invoice immutability, §5.3).',
    )
    plan_name_ar_snapshot = models.CharField(
        max_length=200,
        blank=True,
        default='',
    )

    def __str__(self):
        disp = (self.plan_name_en_snapshot or '').strip()
        if not disp and self.plan_id:
            disp = self.plan.plan_name_en
        return f'{disp} x {self.number_of_cycles} cycles'

    class Meta:
        db_table = 'crm_order_plan_lines'


class OrderAddonLine(models.Model):
    ADDON_TYPE_CHOICES = [
        ('Extra_User', 'Extra Internal User'),
        ('Extra_Internal_Truck', 'Extra Internal Truck'),
        ('Extra_External_Truck', 'Extra External Truck'),
        ('Extra_Driver', 'Extra Driver'),
        ('Extra_Shipment', 'Extra Shipment'),
        ('Extra_Storage_GB', 'Extra Storage (GB)'),
    ]
    ACTION_TYPE_CHOICES = [
        ('Add', 'Add'),
        ('Reduce', 'Reduce'),
    ]

    line_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    order = models.ForeignKey(
        SubscriptionOrder,
        on_delete=models.CASCADE,
        related_name='addon_lines',
    )
    action_type = models.CharField(
        max_length=10,
        choices=ACTION_TYPE_CHOICES,
        default='Add',
    )
    add_on_type = models.CharField(max_length=30, choices=ADDON_TYPE_CHOICES)
    quantity = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    number_of_cycles = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal('1.00'),
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    pro_rata_adjustment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    line_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    add_on_type_label_snapshot = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='English label for add-on type at order time (§5.3).',
    )

    def __str__(self):
        return f'{self.add_on_type} x {self.quantity}'

    class Meta:
        db_table = 'crm_order_addon_lines'


class Transaction(models.Model):
    TYPE_CHOICES = [
        ('Order_Payment', 'Order Payment'),
        ('Wallet_TopUp', 'Wallet Top-Up'),
        ('Refund', 'Refund'),
    ]
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Completed', 'Completed'),
        ('Failed', 'Failed'),
        ('Rejected', 'Rejected'),
    ]

    transaction_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    tenant = models.ForeignKey(
        TenantProfile,
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    order = models.ForeignKey(
        SubscriptionOrder,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='transactions',
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default='Order_Payment',
    )
    payment_method = models.ForeignKey(
        'PaymentMethod',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    currency = models.ForeignKey(
        'Currency',
        on_delete=models.PROTECT,
        related_name='crm_transactions',
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    exchange_rate_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal('1.000000'),
    )
    base_currency_equivalent_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Pending',
    )
    gateway_ref = models.CharField(max_length=100, null=True, blank=True)
    attachment = models.FileField(upload_to='receipts/', null=True, blank=True)
    reviewed_by = models.ForeignKey(
        'AdminUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_transactions',
    )
    review_notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f'TXN-{str(self.transaction_id)[:8]} '
            f'- {self.tenant.company_name} - {self.amount} '
            f'{self.currency_id}'
        )

    class Meta:
        db_table = 'crm_transactions'
        ordering = ['-created_at']


class StandardInvoice(models.Model):
    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Issued', 'Issued'),
        ('Paid', 'Paid'),
        ('Void', 'Void'),
    ]

    invoice_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    invoice_number = models.CharField(max_length=50, unique=True)
    order = models.ForeignKey(
        SubscriptionOrder,
        on_delete=models.PROTECT,
        related_name='invoices',
    )
    tenant = models.ForeignKey(
        TenantProfile,
        on_delete=models.PROTECT,
        related_name='invoices',
    )
    tax_code = models.ForeignKey(
        'TaxCode',
        null=True,
        on_delete=models.SET_NULL,
    )
    issue_date = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='Issued',
    )

    # Snapshot fields (hard-copied at generation)
    supplier_name = models.CharField(max_length=100)
    supplier_name_ar = models.CharField(max_length=100, null=True, blank=True)
    supplier_tax_number = models.CharField(max_length=50)
    supplier_address = models.TextField(null=True, blank=True)
    supplier_support_email = models.EmailField(max_length=100, null=True, blank=True)
    supplier_support_phone = models.CharField(max_length=20, null=True, blank=True)
    supplier_commercial_register = models.CharField(max_length=50, null=True, blank=True)
    
    customer_name = models.CharField(max_length=100)
    customer_tax_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
    )
    customer_address = models.TextField(null=True, blank=True)
    customer_logo_path = models.CharField(max_length=255, null=True, blank=True)

    # Financial fields
    sub_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    taxable_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    grand_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    currency = models.ForeignKey(
        'Currency',
        on_delete=models.PROTECT,
        related_name='standard_invoices',
    )
    exchange_rate_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=Decimal('1.000000'),
    )
    base_currency_equivalent_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.invoice_number

    @property
    def customer_logo_url(self):
        """Resolve a storage-safe URL for Bill To logo snapshot."""
        if not self.customer_logo_path:
            return ''
        from django.conf import settings

        media_url = settings.MEDIA_URL or '/media/'
        if not media_url.endswith('/'):
            media_url = f'{media_url}/'
        path = str(self.customer_logo_path).lstrip('/')
        return f'{media_url}{path}'

    def save(self, *args, **kwargs):
        if self.pk and StandardInvoice.objects.filter(
                invoice_id=self.invoice_id).exists():
            if self.status not in ['Void']:
                raise PermissionError(
                    'Standard Invoices are immutable after generation. '
                    'Only status can be changed to Void.'
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Standard Invoices cannot be deleted.')

    class Meta:
        db_table = 'crm_invoices'
        ordering = ['-issue_date']


class InvoiceLineItem(models.Model):
    line_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    invoice = models.ForeignKey(
        StandardInvoice,
        on_delete=models.PROTECT,
        related_name='line_items',
    )
    item_description = models.CharField(max_length=255)
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('1.00'),
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    line_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )

    def __str__(self):
        return self.item_description

    def save(self, *args, **kwargs):
        if self.pk and InvoiceLineItem.objects.filter(
                line_id=self.line_id).exists():
            raise PermissionError(
                'Invoice line items are immutable after creation.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Invoice line items cannot be deleted.')

    class Meta:
        db_table = 'crm_invoice_line_items'


class SupportCategory(models.Model):
    category_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name_en = models.CharField(max_length=100, unique=True)
    name_ar = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
        related_name='support_categories_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name_en

    class Meta:
        db_table = 'support_categories'
        ordering = ['name_en']


class CannedResponse(models.Model):
    template_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    title = models.CharField(max_length=100, unique=True)
    message_body = models.TextField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
        related_name='canned_responses_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    class Meta:
        db_table = 'support_canned_responses'
        ordering = ['title']


class SupportTicket(models.Model):
    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
        ('Critical', 'Critical'),
    ]
    STATUS_CHOICES = [
        ('New', 'New'),
        ('In_Progress', 'In Progress'),
        ('Pending_Client', 'Pending Client'),
        ('Closed', 'Closed'),
    ]

    ticket_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    ticket_no = models.CharField(
        max_length=20,
        unique=True,
        help_text='Auto-generated e.g. TKT-10001',
    )
    tenant = models.ForeignKey(
        TenantProfile,
        on_delete=models.PROTECT,
        related_name='support_tickets',
    )
    subject = models.CharField(max_length=255)
    description = models.TextField(
        blank=True,
        default='',
        help_text='Initial request detail',
    )
    category = models.ForeignKey(
        SupportCategory,
        on_delete=models.PROTECT,
        related_name='tickets',
    )
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='Medium',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='New',
    )
    assigned_to = models.ForeignKey(
        'AdminUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='assigned_tickets',
    )
    created_by = models.CharField(
        max_length=100,
        help_text='Tenant User ID who opened the ticket',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.ticket_no} - {self.subject}'

    class Meta:
        db_table = 'support_tickets'
        ordering = ['-created_at']

    @classmethod
    def generate_ticket_no(cls):
        last = cls.objects.order_by('-created_at').first()
        if last and last.ticket_no:
            try:
                last_num = int(last.ticket_no.split('-')[1])
                return f"TKT-{str(last_num + 1).zfill(5)}"
            except Exception:
                pass
        return 'TKT-10001'


class TicketReply(models.Model):
    SENDER_TYPE_CHOICES = [
        ('Tenant_User', 'Tenant User'),
        ('Admin_Support', 'Admin Support'),
        ('System_Bot', 'System Bot'),
    ]

    reply_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name='replies',
    )
    sender_type = models.CharField(
        max_length=20,
        choices=SENDER_TYPE_CHOICES,
    )
    sender_id = models.CharField(
        max_length=100,
        help_text='ID of person or bot who sent this',
    )
    message_body = models.TextField()
    attachment = models.FileField(
        upload_to='support_attachments/',
        null=True,
        blank=True,
    )
    is_internal = models.BooleanField(
        default=False,
        help_text='If True, hidden from Tenant completely',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reply on {self.ticket.ticket_no} by {self.sender_type}"

    class Meta:
        db_table = 'support_ticket_replies'
        ordering = ['created_at']

    def save(self, *args, **kwargs):
        if self.pk and TicketReply.objects.filter(
                reply_id=self.reply_id).exists():
            raise PermissionError(
                'Ticket replies are immutable after creation.'
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(
            'Ticket replies cannot be deleted.'
        )
