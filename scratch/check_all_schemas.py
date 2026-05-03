import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname LIKE 't_%' OR nspname = 'public'")
    schemas = [row[0] for row in cursor.fetchall()]
    print(f"All relevant schemas: {schemas}")
    
    for s in schemas:
        cursor.execute("""
            SELECT count(*) 
            FROM information_schema.tables 
            WHERE table_schema = %s AND table_name = 'tenant_client_attachments'
        """, [s])
        count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT count(*) 
            FROM information_schema.tables 
            WHERE table_schema = %s AND table_name = 'tenant_client_accounts'
        """, [s])
        count_acc = cursor.fetchone()[0]
        
        print(f"Schema {s}: attachments={count}, accounts={count_acc}")
