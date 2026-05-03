import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("""
        SELECT table_schema, table_name, table_type 
        FROM information_schema.tables 
        WHERE table_name = 'tenant_client_attachments'
    """)
    rows = cursor.fetchall()
    print("Table info:")
    for row in rows:
        print(f"  - Schema: {row[0]}, Name: {row[1]}, Type: {row[2]}")
