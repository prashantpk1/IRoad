import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection
from iroad_tenants.models import TenantRegistry

regs = TenantRegistry.objects.all()

for reg in regs:
    print(f"\nChecking schema: {reg.schema_name}")
    connection.set_tenant(reg)
    with connection.cursor() as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = 'tenant_client_attachments'", [reg.schema_name])
        cols = sorted([row[0] for row in cursor.fetchall()])
        print(f"Columns: {cols}")
