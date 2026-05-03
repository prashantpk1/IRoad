import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection
from iroad_tenants.models import TenantRegistry
from tenant_workspace.models import TenantClientAccount, TenantClientAttachment

# Simulate middleware setting to public
connection.set_schema_to_public()
print(f"Initial search_path: {connection.get_schema()}")

# Simulate view activation
tid = '18860dff-4d05-4ffe-9353-2f9c729bfbb4'
registry = TenantRegistry.objects.filter(tenant_profile_id=tid).first()
connection.set_tenant(registry)
print(f"After set_tenant: {connection.get_schema()}")

# Simulate TenantClientAccount query
try:
    account_no = 'CA-A0008'
    client_account = TenantClientAccount.objects.filter(account_no=account_no).first()
    print(f"Found client_account: {client_account}")
except Exception as e:
    print(f"TenantClientAccount query failed: {e}")

# Simulate TenantClientAttachment query
try:
    attachments = list(TenantClientAttachment.objects.filter(client_account=client_account))
    print(f"Found {len(attachments)} attachments")
except Exception as e:
    print(f"TenantClientAttachment query failed: {e}")
