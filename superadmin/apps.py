from django.apps import AppConfig


class SuperadminConfig(AppConfig):
    name = 'superadmin'

    def ready(self):
        """
        Ensure comm-log archival periodic task exists when django-celery-beat is enabled.
        """
        try:
            from django.db.utils import OperationalError, ProgrammingError
            from django_celery_beat.models import CrontabSchedule, PeriodicTask
            import json

            schedule, _ = CrontabSchedule.objects.get_or_create(
                minute='0',
                hour='2',
                day_of_week='*',
                day_of_month='*',
                month_of_year='*',
            )
            PeriodicTask.objects.get_or_create(
                name='archive-old-comm-logs-daily',
                defaults={
                    'task': 'iroad.communication.archive_old_comm_logs',
                    'crontab': schedule,
                    'args': json.dumps([90]),
                    'enabled': True,
                },
            )
        except (OperationalError, ProgrammingError):
            # DB is not ready yet (e.g., during migrate start-up).
            pass
        except Exception:
            # Never block app startup for scheduler bootstrap issues.
            pass
