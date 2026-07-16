# Refresh all default notification email templates to IRoute branding.

from django.db import migrations


def refresh_all_email_templates(apps, schema_editor):
    from superadmin.communication_helpers import (
        refresh_all_default_notification_email_templates,
    )

    refresh_all_default_notification_email_templates()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0040_iroute_email_branding_refresh'),
    ]

    operations = [
        migrations.RunPython(refresh_all_email_templates, noop_reverse),
    ]
