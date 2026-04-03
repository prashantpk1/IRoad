"""
Drop all Redis keys for admin panel JWT sessions (admin:session:*).

Uses REDIS_URL from Django settings — works with any host/port/db your .env
points at (localhost, LAN IP, cloud Redis, etc.). No redis-cli required.
"""

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Delete all keys matching admin:session:* using REDIS_URL from settings.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Required: confirm you want to delete matching keys.',
        )

    def handle(self, *args, **options):
        if not options['yes']:
            self.stderr.write(
                'Refusing to run without --yes (safety). '
                'Example: python manage.py clear_admin_redis_sessions --yes'
            )
            return

        masked = self._mask_redis_url(getattr(settings, 'REDIS_URL', ''))
        self.stdout.write(f'Using REDIS_URL: {masked}')

        from superadmin.redis_helpers import get_redis_client

        client = get_redis_client()
        pattern = 'admin:session:*'
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=pattern, count=100)
            if keys:
                deleted += client.delete(*keys)
            if cursor == 0:
                break

        self.stdout.write(
            self.style.SUCCESS(f'Deleted {deleted} key(s) matching {pattern!r}.')
        )

    @staticmethod
    def _mask_redis_url(url: str) -> str:
        if not url or '@' not in url:
            return url or '(empty)'
        try:
            scheme, rest = url.split('://', 1)
            creds, hostpart = rest.rsplit('@', 1)
            if ':' in creds:
                user, _ = creds.split(':', 1)
                return f'{scheme}://{user}:***@{hostpart}'
            return f'{scheme}://***@{hostpart}'
        except ValueError:
            return url
