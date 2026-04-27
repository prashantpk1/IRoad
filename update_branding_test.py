import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from superadmin.models import LegalIdentity

print("Updating Legal Identity branding...")
legal, created = LegalIdentity.objects.get_or_create(
    identity_id='GLOBAL-LEGAL-IDENTITY',
)

legal.company_name_en = 'iRoad Logistics Pro'
legal.company_name_ar = 'آيرود للخدمات اللوجستية'
# Using an existing file from media/legal/
legal.company_logo = 'legal/1774773515133.png.png'
legal.save()

print(f"Updated Identity: {legal.company_name_en}")
print(f"Logo Path: {legal.company_logo.url}")
