"""
mobile_api/models.py

Models for Mobile API — OTP storage for password reset flow.

DriverPasswordResetOTP stores a 6-digit OTP sent to driver email
for the forgot password flow. One active OTP per email at a time.
"""
import uuid
from django.db import models
from django.utils import timezone
from datetime import timedelta
from django_tenants.utils import schema_context


OTP_EXPIRY_MINUTES = 10


def _otp_expiry_minutes_runtime() -> int:
    from django.conf import settings

    return int(
        getattr(
            settings,
            'MOBILE_API_PASSWORD_RESET_OTP_EXPIRY_MINUTES',
            OTP_EXPIRY_MINUTES,
        )
        or OTP_EXPIRY_MINUTES,
    )


def _otp_max_attempts_runtime() -> int:
    from django.conf import settings

    return int(
        getattr(
            settings,
            'MOBILE_API_PASSWORD_RESET_OTP_MAX_ATTEMPTS',
            5,
        )
        or 5,
    )


def _resend_cooldown_seconds() -> int:
    from django.conf import settings

    return int(
        getattr(settings, 'MOBILE_API_PASSWORD_RESET_RESEND_COOLDOWN_SECONDS', 90)
        or 90,
    )


class DriverPasswordResetOTP(models.Model):
    """
    Stores OTP for driver password reset flow.

    Flow:
      1. Forgot Password API → creates/replaces this record
      2. Verify OTP API → checks otp_code + expiry + is_used
      3. New Password API → checks is_verified + sets password
         then marks is_used=True
    """

    class Status(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        VERIFIED = 'Verified', 'Verified'
        USED = 'Used', 'Used'
        EXPIRED = 'Expired', 'Expired'

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    email = models.EmailField(
        db_index=True,
        help_text='Driver email (from TenantUser)'
    )
    tenant_schema = models.CharField(
        max_length=100,
        db_index=True,
        help_text='Tenant schema name for multi-tenant isolation'
    )
    otp_code = models.CharField(
        max_length=6,
        help_text='6-digit OTP code'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    attempts = models.PositiveSmallIntegerField(
        default=0,
        help_text='Number of wrong verification attempts'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        help_text='OTP expires at this time'
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When OTP was verified successfully'
    )
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When password was reset using this OTP'
    )

    class Meta:
        db_table = 'mobile_api_driver_password_reset_otp'
        ordering = ['-created_at']
        verbose_name = 'Driver Password Reset OTP'
        verbose_name_plural = 'Driver Password Reset OTPs'
        indexes = [
            models.Index(
                fields=['tenant_schema', 'email', 'status'],
                name='ma_otp_tenant_email_status',
            ),
        ]

    def __str__(self):
        return f"OTP for {self.email} [{self.status}]"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """OTP is valid if pending, not expired, attempts below configured max."""
        return (
            self.status == self.Status.PENDING
            and not self.is_expired
            and self.attempts < _otp_max_attempts_runtime()
        )

    @classmethod
    def seconds_since_last_issue(cls, email: str, tenant_schema: str) -> float | None:
        """
        Seconds since the most recent OTP row (any status) for this channel.

        None when no prior row exists.
        """
        if not tenant_schema:
            return None
        with schema_context(tenant_schema):
            row = (
                cls.objects.filter(
                    email=email,
                    tenant_schema=tenant_schema,
                )
                .order_by('-created_at')
                .only('created_at')
                .first()
            )
            if row is None:
                return None
            return (timezone.now() - row.created_at).total_seconds()

    @classmethod
    def resend_is_throttled(cls, email: str, tenant_schema: str) -> bool:
        """True when a new OTP should not be issued yet (resend cooldown)."""
        sec = cls.seconds_since_last_issue(email, tenant_schema)
        if sec is None:
            return False
        return sec < float(_resend_cooldown_seconds())

    @property
    def is_verified_and_unused(self) -> bool:
        """True when OTP verified but password not yet reset."""
        return (
            self.status == self.Status.VERIFIED
            and not self.is_expired
        )

    @classmethod
    def create_for_email(
        cls,
        email: str,
        tenant_schema: str,
        otp_code: str,
        *,
        expire_verified: bool = False,
    ) -> 'DriverPasswordResetOTP':
        """
        Create a new OTP record.
        Invalidates any existing pending OTP for same email+schema.

        When ``expire_verified`` is True (authenticated change-password flow),
        prior ``VERIFIED`` rows for the same email+schema are also expired so
        stale verified codes cannot be replayed after a new OTP is issued.
        """
        if not tenant_schema:
            raise ValueError('tenant_schema is required for OTP creation')
        with schema_context(tenant_schema):
            # Invalidate existing pending OTPs
            cls.objects.filter(
                email=email,
                tenant_schema=tenant_schema,
                status=cls.Status.PENDING,
            ).update(status=cls.Status.EXPIRED)
            if expire_verified:
                cls.objects.filter(
                    email=email,
                    tenant_schema=tenant_schema,
                    status=cls.Status.VERIFIED,
                ).update(status=cls.Status.EXPIRED)

            expiry = timezone.now() + timedelta(
                minutes=_otp_expiry_minutes_runtime(),
            )
            return cls.objects.create(
                email=email,
                tenant_schema=tenant_schema,
                otp_code=otp_code,
                expires_at=expiry,
            )

    @classmethod
    def get_valid_otp(
        cls,
        email: str,
        tenant_schema: str,
    ):
        """
        Get the latest valid OTP for email+schema.
        Returns None if not found or expired.
        """
        if not tenant_schema:
            return None
        with schema_context(tenant_schema):
            return cls.objects.filter(
                email=email,
                tenant_schema=tenant_schema,
                status=cls.Status.PENDING,
            ).order_by('-created_at').first()

    @classmethod
    def get_verified_otp(
        cls,
        email: str,
        tenant_schema: str,
    ):
        """
        Get OTP that was verified but not yet used.
        Used in New Password API.
        """
        if not tenant_schema:
            return None
        with schema_context(tenant_schema):
            return cls.objects.filter(
                email=email,
                tenant_schema=tenant_schema,
                status=cls.Status.VERIFIED,
            ).order_by('-created_at').first()
