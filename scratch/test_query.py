import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from superadmin.models import TenantProfile
from iroad_tenants.models import TenantRegistry
from django.db import connection

tid = '18860dff-4d05-4ffe-9353-2f9c729bfbb4'
tenant = TenantProfile.objects.filter(pk=tid).first()

if not tenant:
    print(f"Tenant {tid} not found")
else:
    print(f"Tenant Profile workspace_schema: {tenant.workspace_schema}")
    registry = TenantRegistry.objects.filter(tenant_profile=tenant).first()
    if not registry:
        print("Registry not found")
    else:
        print(f"Registry schema_name: {registry.schema_name}")
        
        if tenant.workspace_schema != registry.schema_name:
            print("WARNING: DISCREPANCY DETECTED!")
        else:
            print("Schema names match.")
            
        print(f"Activating schema: {registry.schema_name}")
        connection.set_tenant(registry)
        
        from tenant_workspace.models import TenantClientAttachment
        try:
            count = TenantClientAttachment.objects.count()
            print(f"TenantClientAttachment count: {count}")
        except Exception as e:
            print(f"Error querying TenantClientAttachment: {e}")
