# Refresh OTP email HTML to IRoute branding and normalize Legal Identity names.

from django.db import migrations


def refresh_iroute_email_branding(apps, schema_editor):
    from superadmin.communication_helpers import (
        refresh_auth_login_otp_email_template_from_defaults,
    )

    LegalIdentity = apps.get_model('superadmin', 'LegalIdentity')
    for row in LegalIdentity.objects.filter(identity_id='GLOBAL-LEGAL-IDENTITY'):
        updates = {}
        for field in ('company_name_en', 'company_name_ar'):
            value = (getattr(row, field, None) or '').strip()
            compact = value.lower().replace(' ', '').replace('_', '').replace('-', '')
            if compact in {'iroad', 'iroadplatform', 'iroadadmin', 'iroadlogistics'} or (
                compact.startswith('iroad')
            ):
                updates[field] = 'IRoute'
        if updates:
            LegalIdentity.objects.filter(pk=row.pk).update(**updates)

    refresh_auth_login_otp_email_template_from_defaults()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0039_role_description_ar'),
    ]

    operations = [
        migrations.RunPython(refresh_iroute_email_branding, noop_reverse),
    ]
