from django.apps import AppConfig


class MobileApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mobile_api'

    def ready(self) -> None:
        # Register django.core.checks (production hardening).
        from mobile_api import checks  # noqa: F401
        from mobile_api.pod_capture import models as pod_capture_models  # noqa: F401
        from mobile_api.hard_pod import models as hard_pod_models  # noqa: F401
        from mobile_api.payment_collection import models as payment_collection_models  # noqa: F401
        from mobile_api.issues import models as issues_models  # noqa: F401
