from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0100_tenantclientcontact_phone_country_codes'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='truckattachment',
                    name='stats',
                    field=models.CharField(
                        choices=[
                            ('Valid', 'Valid'),
                            ('Expired', 'Expired'),
                            ('Does Not Expire', 'Does Not Expire'),
                        ],
                        default='Does Not Expire',
                        editable=False,
                        help_text='Derived expiry status persisted for reporting.',
                        max_length=32,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    ALTER TABLE tenant_truck_attachments
                    ADD COLUMN IF NOT EXISTS stats varchar(32) NOT NULL
                    DEFAULT 'Does Not Expire';
                    """,
                    reverse_sql="""
                    ALTER TABLE tenant_truck_attachments
                    DROP COLUMN IF EXISTS stats;
                    """,
                ),
            ],
        ),
    ]
