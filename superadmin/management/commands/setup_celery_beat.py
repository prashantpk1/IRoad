from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Setup Celery Beat periodic tasks'

    def handle(self, *args, **options):
        from django_celery_beat.models import CrontabSchedule, PeriodicTask
        import json

        # Daily at midnight — cleanup expired tokens
        schedule_daily, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='0',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )

        PeriodicTask.objects.get_or_create(
            name='Daily: Cleanup Expired Auth Tokens',
            defaults={
                'crontab': schedule_daily,
                'task': 'iroad.auth.cleanup_expired_tokens',
                'args': json.dumps([]),
            },
        )

        # Daily at 1am — check subscription expiry
        schedule_expiry, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='1',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )

        PeriodicTask.objects.get_or_create(
            name='Daily: Check Subscription Expiry',
            defaults={
                'crontab': schedule_expiry,
                'task': 'iroad.billing.check_subscription_expiry',
                'args': json.dumps([]),
            },
        )

        # Daily at 2am — apply scheduled plan downgrades (cycle-end)
        schedule_downgrade, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='2',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )

        PeriodicTask.objects.get_or_create(
            name='Daily: Apply Scheduled Plan Downgrades',
            defaults={
                'crontab': schedule_downgrade,
                'task': 'iroad.billing.apply_scheduled_downgrades',
                'args': json.dumps([]),
            },
        )

        self.stdout.write(
            self.style.SUCCESS('✅ Celery Beat periodic tasks registered')
        )

