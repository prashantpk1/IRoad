import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("""
        SELECT table_schema, table_name 
        FROM information_schema.tables 
        WHERE table_name = 'tenant_client_attachments'
    """)
    rows = cursor.fetchall()
    print("Occurrences of 'tenant_client_attachments':")
    for schema, table in rows:
        print(f"  - {schema}.{table}")
        
    cursor.execute("SHOW search_path")
    print(f"\nCurrent search_path: {cursor.fetchone()[0]}")
