from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0085_sir_line_foreign_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='salesinvoicereport',
            name='auto_post',
            field=models.BooleanField(
                default=False,
                help_text='When enabled, child lines are populated from the operational eligibility sweep.',
            ),
        ),
    ]
