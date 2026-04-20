from django.core.mail.backends.smtp import EmailBackend
from django.conf import settings
from .models import CommGateway
import logging
import smtplib

logger = logging.getLogger(__name__)

class DatabaseEmailBackend(EmailBackend):
    """
    Subclass of SMTP EmailBackend that fetches SMTP settings 
    from the database at runtime.
    """
    def __init__(self, *args, **kwargs):
        # Initial instantiation with super defaults or settings.py defaults
        super().__init__(*args, **kwargs)

    def _apply_fallback_smtp(self):
        fallback_user = (getattr(settings, 'FALLBACK_EMAIL_HOST_USER', '') or '').strip()
        fallback_pass = (getattr(settings, 'FALLBACK_EMAIL_HOST_PASSWORD', '') or '').strip()
        if not fallback_user or not fallback_pass:
            return False
        self.host = getattr(settings, 'FALLBACK_EMAIL_HOST', 'smtp.gmail.com')
        self.port = getattr(settings, 'FALLBACK_EMAIL_PORT', 587)
        self.username = fallback_user
        self.password = fallback_pass
        self.use_tls = bool(getattr(settings, 'FALLBACK_EMAIL_USE_TLS', True))
        self.use_ssl = bool(getattr(settings, 'FALLBACK_EMAIL_USE_SSL', False))
        return True

    def open(self):
        if self.connection:
            return False

        try:
            # Fetch active email gateway
            gateway = CommGateway.objects.filter(
                gateway_type='Email', 
                is_active=True
            ).first()

            if not gateway:
                logger.warning(
                    'No active Email CommGateway in DB; using EMAIL_* from settings.py.',
                )
                if not self.host:
                    return False
            else:
                self.host = gateway.host_url.strip()
                enc = gateway.encryption_type or 'TLS'
                port = gateway.port
                if port is None:
                    port = 465 if enc == 'SSL' else 587
                self.port = port
                self.username = gateway.username_key
                self.password = gateway.password_secret
                self.use_tls = enc == 'TLS'
                self.use_ssl = enc == 'SSL'
                
                # Timeout can be added if needed from a global setting
                self.timeout = getattr(settings, 'EMAIL_TIMEOUT', None)

            # Gmail and most SMTP relays require AUTH. If active config does not
            # provide credentials, force fallback credentials before opening.
            if not (self.username and self.password):
                self._apply_fallback_smtp()

            try:
                return super().open()
            except smtplib.SMTPAuthenticationError:
                if not self._apply_fallback_smtp():
                    raise

                logger.warning(
                    'Primary SMTP auth failed; retrying with fallback SMTP account.',
                )
                return super().open()
        except Exception as e:
            logger.error(f"Failed to open connection using DatabaseEmailBackend: {e}")
            if not self.fail_silently:
                raise
            return False
