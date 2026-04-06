from django.core.management.base import BaseCommand

from superadmin.billing_helpers import apply_due_scheduled_downgrades


class Command(BaseCommand):
    help = (
        'Apply tenant plan downgrades that are scheduled for today or earlier '
        '(subscription cycle end). Safe to run manually or via cron.'
    )

    def handle(self, *args, **options):
        n = apply_due_scheduled_downgrades()
        self.stdout.write(
            self.style.SUCCESS(f'Applied {n} scheduled downgrade(s).'),
        )
