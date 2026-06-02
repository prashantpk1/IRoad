from django.db import migrations, models


ROLE_DESCRIPTION_AR = {
    'Super Admin': 'صلاحية كاملة لجميع الوحدات والإعدادات',
    'Sales': 'يدير إعداد المستأجرين وطلبات الاشتراك',
    'Support': 'يتولى تذاكر الدعم والتواصل مع المستأجرين',
}


def populate_role_description_ar(apps, schema_editor):
    Role = apps.get_model('superadmin', 'Role')
    for role_name_en, description_ar in ROLE_DESCRIPTION_AR.items():
        Role.objects.filter(role_name_en=role_name_en).update(description_ar=description_ar)


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0038_push_dashboard_lookup_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='role',
            name='description_ar',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.RunPython(populate_role_description_ar, migrations.RunPython.noop),
    ]
