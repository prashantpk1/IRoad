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
    print(f"Tenant found: {tenant.company_name}")
    registry = TenantRegistry.objects.filter(tenant_profile=tenant).first()
    if not registry:
        print("Registry not found")
    else:
        print(f"Schema name: {registry.schema_name}")
        connection.set_tenant(registry)
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s", [registry.schema_name])
            tables = [row[0] for row in cursor.fetchall()]
            print("Tables in schema:")
            for t in sorted(tables):
                print(f"  - {t}")
            
            if 'tenant_client_attachments' in tables:
                print("\nSUCCESS: tenant_client_attachments EXISTS")
            else:
                print("\nFAILURE: tenant_client_attachments MISSING")
