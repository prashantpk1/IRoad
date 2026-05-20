from django.apps import AppConfig


class MobileApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mobile_api'

    def ready(self) -> None:
        # Register django.core.checks (production hardening).
        from mobile_api import checks  # noqa: F401
