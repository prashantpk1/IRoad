import json

from django.db import migrations


def create_archive_comm_logs_periodic_task(apps, schema_editor):
    CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute='0',
        hour='2',
        day_of_week='*',
        day_of_month='*',
        month_of_year='*',
        timezone='Asia/Riyadh',
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


def remove_archive_comm_logs_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    PeriodicTask.objects.filter(name='archive-old-comm-logs-daily').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0019_pushdevicetoken'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(
            create_archive_comm_logs_periodic_task,
            remove_archive_comm_logs_periodic_task,
        ),
    ]
