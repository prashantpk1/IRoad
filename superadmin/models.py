from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
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
