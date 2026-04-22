from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='AutoNumberConfiguration',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('form_code', models.CharField(max_length=100, unique=True)),
                ('form_label', models.CharField(max_length=150)),
                ('next_number', models.PositiveBigIntegerField(default=1)),
                ('number_of_digits', models.PositiveSmallIntegerField(default=4)),
                (
                    'sequence_format',
                    models.CharField(
                        choices=[
                            ('numeric', 'Numeric'),
                            ('alpha', 'Alphabetic'),
                            ('alphanumeric', 'Alphanumeric'),
                        ],
                        default='numeric',
                        max_length=20,
                    ),
                ),
                ('is_unique', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'tenant_auto_number_configuration',
            },
        ),
    ]
