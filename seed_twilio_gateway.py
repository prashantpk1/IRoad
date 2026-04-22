import os
import django
from decouple import config

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from superadmin.models import CommGateway

def seed_twilio_mock():
    # Only one active per type (Singularity Rule will handle deactivation of others)
    gw, created = CommGateway.objects.update_or_create(
        provider_name='Twilio',
        gateway_type='SMS',
        defaults={
            'host_url': config('TWILIO_HOST_URL', default='https://api.twilio.com/2010-04-01/Accounts'),
            'username_key': config('TWILIO_ACCOUNT_SID', default=''),
            'password_secret': config('TWILIO_AUTH_TOKEN', default=''),
            'sender_id': config('TWILIO_SENDER_ID', default=''),
            'is_active': True,
        }
    )
    if created:
        print(f"Created Mock Twilio Gateway: {gw.gateway_id}")
    else:
        print(f"Updated Mock Twilio Gateway: {gw.gateway_id}")

if __name__ == '__main__':
    seed_twilio_mock()
