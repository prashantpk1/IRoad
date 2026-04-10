import os
import django
import uuid
from django.core.mail import send_mail
from django.conf import settings

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from superadmin.models import CommGateway, AdminUser

def test_comm_gateways():
    print("--- Testing Communication Gateways ---")
    
    # Get or create a dummy admin user for updated_by
    admin_user = AdminUser.objects.first()
    if not admin_user:
        print("Error: No AdminUser found to associate with gateways.")
        return

    # 1. Test Singularity Rule
    print("Testing Singularity Rule...")
    
    # Clean up any existing test gateways
    CommGateway.objects.filter(provider_name__startswith="Test ").delete()
    
    # Create first active Email gateway
    g1 = CommGateway.objects.create(
        gateway_id=uuid.uuid4(),
        gateway_type='Email',
        provider_name="Test Gmail",
        host_url="smtp.gmail.com",
        port=587,
        username_key="test1@gmail.com",
        password_secret="pass1",
        encryption_type='TLS',
        is_active=True,
        updated_by=admin_user
    )
    print(f"Created G1: {g1.provider_name}, Active: {g1.is_active}")
    
    # Create second active Email gateway
    g2 = CommGateway.objects.create(
        gateway_id=uuid.uuid4(),
        gateway_type='Email',
        provider_name="Test Mailgun",
        host_url="smtp.mailgun.org",
        port=587,
        username_key="test2@mailgun.org",
        password_secret="pass2",
        encryption_type='TLS',
        is_active=True,
        updated_by=admin_user
    )
    print(f"Created G2: {g2.provider_name}, Active: {g2.is_active}")
    
    # Refresh G1
    g1.refresh_from_db()
    print(f"Refreshed G1 Active status: {g1.is_active} (Expected: False)")
    
    if not g1.is_active and g2.is_active:
        print("SUCCESS: Singularity Rule enforced at model level.")
    else:
        print("FAILURE: Singularity Rule NOT enforced.")

    # 2. Test DatabaseEmailBackend
    print("\nTesting DatabaseEmailBackend...")
    print(f"Current EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
    
    # We won't actually send an email (to avoid real SMTP errors), 
    # but we will check if the connection parameters are correctly fetched.
    from django.core.mail import get_connection
    connection = get_connection()
    
    # Force open() to see if it pulls from DB
    # Note: open() calls super().open() which might fail if hosts are fake, 
    # but we can check the attributes after they are set in DatabaseEmailBackend.open()
    try:
        connection.open()
    except Exception:
        pass # Expected to fail connection if credentials are fake
    
    print(f"Connection Host: {connection.host} (Expected: {g2.host_url})")
    print(f"Connection Port: {connection.port} (Expected: {g2.port})")
    print(f"Connection User: {connection.username} (Expected: {g2.username_key})")
    
    if connection.host == g2.host_url and connection.username == g2.username_key:
        print("SUCCESS: DatabaseEmailBackend correctly fetched active gateway settings.")
    else:
        print("FAILURE: DatabaseEmailBackend did not fetch settings.")

    # Cleanup
    CommGateway.objects.filter(provider_name__startswith="Test ").delete()
    print("\nCleanup complete.")

if __name__ == "__main__":
    test_comm_gateways()
