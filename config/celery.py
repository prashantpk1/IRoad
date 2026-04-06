import os

from celery import Celery
from celery.signals import task_prerun

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('iroad')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@task_prerun.connect
def _celery_reset_db_schema_to_public(**_kwargs):
    """Tasks default to public schema (CP master data)."""
    try:
        from django.db import connection

        connection.set_schema_to_public()
    except Exception:
        pass

