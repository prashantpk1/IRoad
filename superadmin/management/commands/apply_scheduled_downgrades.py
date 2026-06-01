from django.core.management.base import BaseCommand

from superadmin.billing_helpers import process_due_subscription_billing


class Command(BaseCommand):
    help = (
        'Apply due plan downgrades and suspend tenants past subscription grace. '
        'Safe to run manually or via cron when Celery Beat is not running.'
    )

    def handle(self, *args, **options):
        result = process_due_subscription_billing()
        self.stdout.write(
            self.style.SUCCESS(
                'Applied %(scheduled_downgrades_applied)s scheduled downgrade(s); '
                'suspended %(tenants_suspended)s tenant(s).'
                % result
            ),
        )
