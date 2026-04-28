import secrets
from datetime import timedelta
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings

from superadmin.communication_helpers import (
    _normalize_from_email_header,
    send_named_notification_email,
)


def get_security_settings():
    from superadmin.models import AdminSecuritySettings

    try:
        return AdminSecuritySettings.objects.get(setting_id="ADMIN-SEC-CONF")
    except AdminSecuritySettings.DoesNotExist:

        class Defaults:
            session_timeout_minutes = 1440
            max_failed_logins = 3
            lockout_duration_minutes = 30

        return Defaults()


def check_brute_force(email):
    """
    Returns dict:
    {
      'is_locked': True/False,
      'remaining_minutes': int,
      'failed_count': int
    }
    """
    from superadmin.models import LoginAttempt

    settings = get_security_settings()

    try:
        attempt = LoginAttempt.objects.get(email=email)
    except LoginAttempt.DoesNotExist:
        return {
            "is_locked": False,
            "remaining_minutes": 0,
            "failed_count": 0,
        }

    if attempt.locked_at:
        lockout_end = attempt.locked_at + timedelta(
            minutes=settings.lockout_duration_minutes
        )
        if timezone.now() < lockout_end:
            remaining_minutes = (
                int((lockout_end - timezone.now()).total_seconds() / 60) + 1
            )
            remaining_seconds = int((lockout_end - timezone.now()).total_seconds())
            return {
                "is_locked": True,
                "remaining_minutes": remaining_minutes,
                "remaining_seconds": max(0, remaining_seconds),
                "failed_count": attempt.failed_count,
            }
        else:
            # Lockout expired — reset
            attempt.failed_count = 0
            attempt.locked_at = None
            attempt.save()

    return {
        "is_locked": False,
        "remaining_minutes": 0,
        "failed_count": attempt.failed_count,
    }


def record_failed_attempt(email):
    """Increment failed count. Lock if max reached."""
    from superadmin.models import LoginAttempt

    settings = get_security_settings()

    attempt, _ = LoginAttempt.objects.get_or_create(email=email)
    attempt.failed_count += 1

    if attempt.failed_count >= settings.max_failed_logins:
        attempt.locked_at = timezone.now()

    attempt.save()


def reset_failed_attempts(email):
    """Call this on successful login."""
    from superadmin.models import LoginAttempt

    LoginAttempt.objects.filter(email=email).update(
        failed_count=0,
        locked_at=None,
    )


def create_auth_token(admin_user, token_type):
    """
    Creates and returns a new token.
    token_type: 'invite' or 'password_reset'
    """
    from superadmin.models import AdminAuthToken

    expiry_hours = 24 if token_type == "invite" else 1

    # Invalidate any existing unused tokens of same type
    AdminAuthToken.objects.filter(
        admin_user=admin_user,
        token_type=token_type,
        is_used=False,
    ).update(is_used=True)

    token = AdminAuthToken.objects.create(
        admin_user=admin_user,
        token=secrets.token_urlsafe(32),
        token_type=token_type,
        expires_at=timezone.now() + timedelta(hours=expiry_hours),
    )
    return token


def log_access(attempt_type, status, email_used, ip_address=None):
    """Create immutable access log entry."""
    from superadmin.models import AccessLog

    AccessLog(
        attempt_type=attempt_type,
        status=status,
        user_domain="Admin",
        email_used=email_used,
        ip_address=ip_address,
    ).save()


def send_auth_email(user, email_type, context):
    """
    Renders and sends an authentication-related email.
    email_type: 'password_reset' or 'invite'
    """
    if email_type == 'password_reset':
        subject = 'Reset Your iRoad Password'
        template_name = 'auth/emails/password_reset.html'
        notif_template_name = 'AUTH_PASSWORD_RESET'
    elif email_type == 'invite':
        subject = 'Activate Your iRoad Admin Account'
        template_name = 'auth/emails/user_invite.html'
        notif_template_name = 'AUTH_ADMIN_INVITE'
    else:
        return False

    try:
        # Prefer Notification Templates configured from CP UI.
        if send_named_notification_email(
            notif_template_name,
            recipient_email=user.email,
            context_dict=context,
            language='en',
            default_subject=subject,
            trigger_source=f'TemplateName: {notif_template_name}',
            # Auth flows should stay on Django SMTP defaults for consistency.
            force_django_smtp=True,
        ):
            return True

        html_content = render_to_string(template_name, context)
        text_content = strip_tags(html_content)

        from_email = _normalize_from_email_header(
            getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
            getattr(settings, 'EMAIL_HOST_USER', ''),
        )
        msg = EmailMultiAlternatives(
            subject,
            text_content,
            from_email,
            [user.email]
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        return True
    except Exception as e:
        # In a real production system, consider logging this error
        # to an observability platform.
        print(f"Error sending {email_type} email to {user.email}: {e}")
        return False

