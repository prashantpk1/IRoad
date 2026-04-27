import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'iroad.settings') # Need correct settings path
try:
    from django.conf import settings
    # Try finding settings if it fails
    if not os.path.exists('iroad/settings.py'):
        if os.path.exists('config/settings.py'):
            os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    django.setup()
    from superadmin.models import Role
    from django.db.models import Window, F
    from django.db.models.functions import RowNumber
    
    qs = Role.objects.annotate(
        rank=Window(expression=RowNumber(), order_by=F('created_at').asc())
    )
    list(qs[:5])
    print("Window functions supported")
except Exception as e:
    print(f"Error: {e}")
