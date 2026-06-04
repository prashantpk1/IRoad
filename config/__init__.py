from . import django_compat  # noqa: F401 — Python 3.14 + Django 5.0 template context fix

from .celery import app as celery_app

__all__ = ('celery_app',)
