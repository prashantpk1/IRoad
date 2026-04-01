import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name='iroad.auth.cleanup_expired_tokens', bind=True, max_retries=3)
def cleanup_expired_tokens(self):
    """
    Periodic task: Clean up expired AdminAuthTokens from DB.
    Runs daily via Celery Beat.
    """
    try:
        from superadmin.models import AdminAuthToken

        deleted_count, _ = AdminAuthToken.objects.filter(
            expires_at__lt=timezone.now(),
            is_used=False,
        ).delete()
        logger.info(f'Cleaned up {deleted_count} expired auth tokens')
        return {'deleted': deleted_count}
    except Exception as exc:
        logger.error(f'cleanup_expired_tokens failed: {exc}')
        raise self.retry(exc=exc, countdown=300)


@shared_task(name='iroad.auth.revoke_admin_sessions', bind=True, max_retries=3)
def revoke_admin_sessions_task(self, admin_id):
    """
    Kill Switch: Revoke all Redis sessions for a suspended admin.
    Called by AdminUserToggleStatusView on suspend.
    """
    try:
        from superadmin.redis_helpers import revoke_all_sessions_for_admin

        revoke_all_sessions_for_admin(admin_id)
        logger.info(f'Revoked all sessions for admin: {admin_id}')
        return {'admin_id': admin_id, 'status': 'revoked'}
    except Exception as exc:
        logger.error(f'revoke_admin_sessions_task failed: {exc}')
        raise self.retry(exc=exc, countdown=10)


@shared_task(name='iroad.auth.revoke_tenant_sessions', bind=True, max_retries=3)
def revoke_tenant_sessions_task(self, tenant_id):
    """
    Kill Switch: Revoke all Redis sessions for a suspended tenant.
    Phase 8: called when tenant account_status → Suspended.
    """
    try:
        from superadmin.redis_helpers import revoke_all_tenant_sessions

        revoke_all_tenant_sessions(tenant_id)
        logger.info(f'Revoked all sessions for tenant: {tenant_id}')
        return {'tenant_id': tenant_id, 'status': 'revoked'}
    except Exception as exc:
        logger.error(f'revoke_tenant_sessions_task failed: {exc}')
        raise self.retry(exc=exc, countdown=10)


@shared_task(name='iroad.communication.send_email', bind=True, max_retries=3)
def send_email_task(self, recipient, subject, body, template_id=None):
    """
    Send email via active SMTP gateway (FRM-CP-05-01).
    Phase 7: reads active gateway credentials from DB.
    TODO Phase 7: implement full SMTP dispatch here.
    """
    try:
        logger.info(f'Email task queued for: {recipient}')
        # TODO Phase 7: implement below
        # from superadmin.models import CommunicationGateway
        # gateway = CommunicationGateway.objects.get(
        #     gateway_type='Email', is_active=True)
        # send via smtplib using gateway credentials
        return {
            'recipient': recipient,
            'status': 'queued',
            'note': 'Phase 7 implementation pending',
        }
    except Exception as exc:
        logger.error(f'send_email_task failed: {exc}')
        raise self.retry(exc=exc, countdown=60)


@shared_task(name='iroad.communication.send_sms', bind=True, max_retries=3)
def send_sms_task(self, recipient_phone, message, template_id=None):
    """
    Send SMS via active SMS gateway (FRM-CP-05-01).
    Phase 7: reads active gateway credentials from DB.
    TODO Phase 7: implement full SMS dispatch here.
    """
    try:
        logger.info(f'SMS task queued for: {recipient_phone}')
        # TODO Phase 7: implement below
        return {
            'recipient': recipient_phone,
            'status': 'queued',
            'note': 'Phase 7 implementation pending',
        }
    except Exception as exc:
        logger.error(f'send_sms_task failed: {exc}')
        raise self.retry(exc=exc, countdown=60)


@shared_task(name='iroad.billing.check_subscription_expiry', bind=True, max_retries=3)
def check_subscription_expiry_task(self):
    """
    Daily cron: Check expired subscriptions.
    Phase 8: auto-suspend tenants past grace period.
    TODO Phase 8: implement full expiry logic here.
    """
    try:
        logger.info('Subscription expiry check task running')
        # TODO Phase 8: implement below
        # from superadmin.models import TenantProfile
        # from superadmin.auth_helpers import get_security_settings
        # settings = get_security_settings()
        # grace_days = GlobalSystemRules.grace_period_days
        # expired = TenantProfile.objects.filter(
        #     subscription_expiry_date__lt=today - grace_days,
        #     account_status='Active'
        # )
        # for tenant in expired:
        #     tenant.account_status = 'Suspended_Billing'
        #     tenant.save()
        #     revoke_tenant_sessions_task.delay(tenant.tenant_id)
        return {'status': 'completed', 'note': 'Phase 8 implementation pending'}
    except Exception as exc:
        logger.error(f'check_subscription_expiry_task failed: {exc}')
        raise self.retry(exc=exc, countdown=3600)

