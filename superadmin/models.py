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
    session_timeout_minutes = models.IntegerField(default=240)
    max_failed_logins = models.IntegerField(default=3)
    lockout_duration_minutes = models.IntegerField(default=30)
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

    def is_valid_for_use(self):
        from django.utils import timezone
        if not self.is_active:
            return False, "Promo code is inactive."
        now = timezone.now()
        if now < self.valid_from:
            return False, "Promo code is not yet valid."
        if self.valid_until and now > self.valid_until:
            return False, "Promo code has expired."
        if self.max_uses is not None and \
                self.current_uses >= self.max_uses:
            return False, "Promo code usage limit reached."
        return True, "Valid"


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
    updated_by = models.ForeignKey(
        'AdminUser',
        null=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider_name} ({self.gateway_type})"

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
