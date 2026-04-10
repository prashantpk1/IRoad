import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from superadmin.models import CommGateway

def seed_twilio_mock():
    # Only one active per type (Singularity Rule will handle deactivation of others)
    gw, created = CommGateway.objects.update_or_create(
        provider_name='Twilio',
        gateway_type='SMS',
        defaults={
            'host_url': 'http://localhost:8000/api/v1/mock/twilio/',
            'username_key': 'AC_MOCK_SID_12345',
            'password_secret': 'MOCK_TOKEN_67890',
            'sender_id': '+15551234567',
            'is_active': True,
        }
    )
    if created:
        print(f"Created Mock Twilio Gateway: {gw.gateway_id}")
    else:
        print(f"Updated Mock Twilio Gateway: {gw.gateway_id}")

if __name__ == '__main__':
    seed_twilio_mock()
