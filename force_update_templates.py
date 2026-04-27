import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from superadmin.models import NotificationTemplate
from superadmin.communication_helpers import DEFAULT_NOTIFICATION_EMAIL_TEMPLATES

print("Force updating default notification templates in DB...")
count = 0
for item in DEFAULT_NOTIFICATION_EMAIL_TEMPLATES:
    t = NotificationTemplate.objects.filter(template_name=item['template_name']).first()
    if t:
        print(f"Updating: {t.template_name}")
        t.subject_en = item['subject_en']
        t.subject_ar = item['subject_ar']
        t.body_en = item['body_en']
        t.body_ar = item['body_ar']
        t.save()
        count += 1
    else:
        print(f"Creating new: {item['template_name']}")
        NotificationTemplate.objects.create(
            template_name=item['template_name'],
            channel_type='Email',
            category=item['category'],
            subject_en=item['subject_en'],
            subject_ar=item['subject_ar'],
            body_en=item['body_en'],
            body_ar=item['body_ar'],
            is_active=True
        )
        count += 1

print(f"Successfully updated/synchronized {count} templates.")
