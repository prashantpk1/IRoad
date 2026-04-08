from django.core.mail.backends.smtp import EmailBackend
from django.conf import settings
from .models import CommGateway
import logging

logger = logging.getLogger(__name__)

class DatabaseEmailBackend(EmailBackend):
    """
    Subclass of SMTP EmailBackend that fetches SMTP settings 
    from the database at runtime.
    """
    def __init__(self, *args, **kwargs):
        # Initial instantiation with super defaults or settings.py defaults
        super().__init__(*args, **kwargs)

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
                logger.warning("No active Email Gateway found in DB. Falling back to settings.py or failing.")
                # If no gateway in DB, we can either fail or use settings.py
                # Spec says "All email in the system will go according the SMTP configuration"
                # so we probably shouldn't fall back to hardcoded settings if we want to enforce this.
                if not self.host:
                    return False
            else:
                self.host = gateway.host_url
                self.port = gateway.port
                self.username = gateway.username_key
                self.password = gateway.password_secret
                
                # encryption_type enum: [TLS, SSL, None]
                self.use_tls = (gateway.encryption_type == 'TLS')
                self.use_ssl = (gateway.encryption_type == 'SSL')
                
                # Timeout can be added if needed from a global setting
                self.timeout = getattr(settings, 'EMAIL_TIMEOUT', None)

            return super().open()
        except Exception as e:
            logger.error(f"Failed to open connection using DatabaseEmailBackend: {e}")
            if not self.fail_silently:
                raise
            return False
