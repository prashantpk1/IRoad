import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection
from iroad_tenants.models import TenantRegistry
from tenant_workspace.models import TenantClientAccount, TenantClientAttachment

def test_activation(tid):
    print(f"\nTesting activation for tid: {tid}")
    connection.set_schema_to_public()
    print(f"Schema before: {connection.get_schema()}")
    
    registry = TenantRegistry.objects.select_related('tenant_profile').filter(tenant_profile_id=tid).first()
    if not registry:
        print("Registry not found!")
        return
        
    print(f"Found registry: {registry.schema_name}")
    connection.set_tenant(registry)
    print(f"Schema after: {connection.get_schema()}")
    print(f"Current tenant: {connection.tenant}")
    
    with connection.cursor() as cursor:
        cursor.execute("SHOW search_path")
        print(f"Postgres search_path: {cursor.fetchone()[0]}")
        
        cursor.execute("SELECT count(*) FROM tenant_client_attachments")
        print(f"Table query count: {cursor.fetchone()[0]}")

tid = '18860dff-4d05-4ffe-9353-2f9c729bfbb4'
test_activation(tid)
