import sys

from django.apps import AppConfig


class SuperadminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'superadmin'

    def ready(self):
        # Avoid probing during management commands that do not need Redis.
        argv = set(sys.argv[1:2])
        if argv & {'migrate', 'makemigrations', 'test', 'shell', 'collectstatic'}:
            return
        from superadmin.redis_helpers import probe_redis_at_startup

        probe_redis_at_startup()
