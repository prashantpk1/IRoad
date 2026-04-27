import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from superadmin.models import NotificationTemplate
from superadmin.communication_helpers import render_notification_template, _build_branding_context

print("--- FINAL VERIFICATION ---")

# 1. Check Branding Context
branding = _build_branding_context()
print(f"Current Branding: {branding['brand_company_name']}")

# 2. Render AUTH_LOGIN_OTP
otp_template = NotificationTemplate.objects.filter(template_name='AUTH_LOGIN_OTP').first()
if otp_template:
    subject, body = render_notification_template(otp_template, {'otp_code': '123456'})
    print(f"\nOTP Template Body Snippet:")
    # Look for the company name in the body
    if branding['brand_company_name'] in body:
        print(f"SUCCESS: Found '{branding['brand_company_name']}' in OTP body!")
    else:
        print(f"FAILURE: Did NOT find branding in OTP body. Found instead: {body[:500]}...")
else:
    print("OTP Template not found!")

# 3. Render TENANT_WELCOME_EMAIL
welcome_template = NotificationTemplate.objects.filter(template_name='TENANT_WELCOME_EMAIL').first()
if welcome_template:
    subject, body = render_notification_template(welcome_template, {'company_name': 'Test Client'})
    print(f"\nWelcome Template Body Snippet:")
    if branding['brand_company_name'] in body:
        print(f"SUCCESS: Found '{branding['brand_company_name']}' in Welcome body!")
    else:
        print(f"FAILURE: Did NOT find branding in Welcome body.")
else:
    print("Welcome Template not found!")
