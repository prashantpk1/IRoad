import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from superadmin.communication_helpers import _build_branding_context
from superadmin.models import LegalIdentity

print("Buidling branding context...")
ctx = _build_branding_context()
print(f"Context: {ctx}")

legal = LegalIdentity.objects.filter(identity_id='GLOBAL-LEGAL-IDENTITY').first()
if legal:
    print(f"Legal record found: {legal.company_name_en}")
else:
    print("Legal record NOT found!")
