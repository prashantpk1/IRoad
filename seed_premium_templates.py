import os
import sys
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force UTF-8 output to avoid UnicodeEncodeError on Windows consoles.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

django.setup()

from superadmin.models import NotificationTemplate
from superadmin.communication_helpers import DEFAULT_NOTIFICATION_EMAIL_TEMPLATES

def seed_premium_templates():
    print("\n--- Seeding Premium Notification Templates ---")
    
    for template_data in DEFAULT_NOTIFICATION_EMAIL_TEMPLATES:
        template_name = template_data['template_name']
        
        # We use template_name as the primary key for seeding here
        template, created = NotificationTemplate.objects.get_or_create(
            template_name=template_name,
            defaults=template_data
        )
        
        if not created:
            # Force update to premium design
            print(f"  🔄 Updating existing template: {template_name}")
            for key, value in template_data.items():
                setattr(template, key, value)
            template.save()
        else:
            print(f"  ✅ Created new template: {template_name}")

    print("\n✨ Seeding completed successfully.")

if __name__ == "__main__":
    seed_premium_templates()
