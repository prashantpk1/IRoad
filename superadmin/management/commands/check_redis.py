from django.conf import settings
from django.core.management.base import BaseCommand
import os

from superadmin.redis_helpers import redis_health_check, reset_redis_client


class Command(BaseCommand):
    help = 'Verify Redis connectivity for tenant/admin sessions and Celery.'

    def handle(self, *args, **options):
        reset_redis_client()
        redis_url = getattr(settings, 'REDIS_URL', '')
        self.stdout.write(f'Redis URL: {redis_url}')

        if redis_health_check():
            self.stdout.write(self.style.SUCCESS('Redis connection OK.'))
            return

        self.stdout.write(self.style.ERROR('Redis is not reachable.'))
        self.stdout.write('')
        if os.path.exists('/.dockerenv'):
            self.stdout.write('Running inside Docker — Redis host must be "redis", not 127.0.0.1.')
        else:
            self.stdout.write('Running on host — Redis must listen on 127.0.0.1:6379 (iroad-redis container).')
            self.stdout.write('Do not set REDIS_URL=redis://redis:6379/0 in .env when using host runserver.')
        self.stdout.write('')
        self.stdout.write('Start Redis:  docker compose up -d redis')
        self.stdout.write('Or rebuild web: docker compose up -d --build web')
