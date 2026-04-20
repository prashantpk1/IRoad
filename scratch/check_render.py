import os
import sys
import django
from django.template import Context, Template
from django.conf import settings

# Add current directory to path
sys.path.append(os.getcwd())

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from superadmin.models import NotificationTemplate, TenantProfile
from superadmin.communication_helpers import _build_branding_context

def test_render():
    print("Testing TENANT_WELCOME_EMAIL rendering...")
    
    # Try to find a tenant for context
    tenant = TenantProfile.objects.first()
    if not tenant:
        print("No tenant found, using fallback context.")
        tenant_context = {'primary_email': 'test@example.com', 'tenant_id': 'TEN-123'}
    else:
        tenant_context = tenant

    # Build context similar to send_tenant_welcome_email
    branding = _build_branding_context()
    context_data = {
        'tenant': tenant_context,
        'company_name': tenant.legal_name if tenant and hasattr(tenant, 'legal_name') else 'Test Company',
        'portal_bootstrap_password': 'BOOTSTRAP-PASS-123',
        'portal_login_url': 'https://iru.iroad.com/login/',
        **branding
    }

    # Find the template in DB or use the DEFAULT from code
    from superadmin.communication_helpers import DEFAULT_NOTIFICATION_EMAIL_TEMPLATES
    welcome_template_data = next((t for t in DEFAULT_NOTIFICATION_EMAIL_TEMPLATES if t['template_name'] == 'TENANT_WELCOME_EMAIL'), None)
    
    if not welcome_template_data:
        print("FAILURE: Could not find TENANT_WELCOME_EMAIL in DEFAULT_NOTIFICATION_EMAIL_TEMPLATES")
        return

    print("Rendering English Version...")
    tmpl_en = Template(welcome_template_data['body_en'])
    rendered_en = tmpl_en.render(Context(context_data))
    
    with open('scratch/rendered_welcome_en.html', 'w', encoding='utf-8') as f:
        f.write(rendered_en)
    print("English version saved to scratch/rendered_welcome_en.html")

    print("Rendering Arabic Version...")
    tmpl_ar = Template(welcome_template_data['body_ar'])
    rendered_ar = tmpl_ar.render(Context(context_data))
    
    with open('scratch/rendered_welcome_ar.html', 'w', encoding='utf-8') as f:
        f.write(rendered_ar)
    print("Arabic version saved to scratch/rendered_welcome_ar.html")
    
    # Check if Tenant ID and API Bridge Key are present in the output
    if 'Tenant Identifier' in rendered_en or 'X-Tenant-ID' in rendered_en:
        print("WARNING: 'Tenant Identifier' still present in English render!")
    else:
        print("SUCCESS: 'Tenant Identifier' removed from English render.")
        
    if 'API Bridge Key' in rendered_en:
         print("WARNING: 'API Bridge Key' still present in English render!")
    else:
        print("SUCCESS: 'API Bridge Key' removed from English render.")

if __name__ == "__main__":
    test_render()
