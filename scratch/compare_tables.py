import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    for table in ['tenant_client_accounts', 'tenant_client_attachments']:
        cursor.execute("""
            SELECT table_schema, table_name 
            FROM information_schema.tables 
            WHERE table_name = %s
        """, [table])
        rows = cursor.fetchall()
        print(f"Occurrences of '{table}':")
        if not rows:
            print("  (none)")
        for schema, table_name in rows:
            print(f"  - {schema}.{table_name}")
