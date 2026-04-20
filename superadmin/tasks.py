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
    Send email: active CommGateway (SMTP) when configured, else Django email backend.
    """
    try:
        from superadmin.communication_helpers import send_transactional_email

        trigger_source = f'Template: {template_id}' if template_id else 'Task: Email'
        send_transactional_email(
            recipient,
            subject,
            body,
            html_body=None,
            trigger_source=trigger_source,
        )
        return {'recipient': recipient, 'status': 'sent'}
    except Exception as exc:
        logger.error(f'send_email_task failed: {exc}')
        raise self.retry(exc=exc, countdown=60)


@shared_task(name='iroad.communication.send_sms', bind=True, max_retries=3)
def send_sms_task(self, recipient_phone, message, template_id=None):
    """
    Send SMS: JSON POST to active gateway ``host_url`` (see ``communication_helpers``).
    """
    try:
        from superadmin.communication_helpers import send_transactional_sms

        trigger_source = f'Template: {template_id}' if template_id else 'Task: SMS'
        ok = send_transactional_sms(
            recipient_phone,
            message,
            trigger_source=trigger_source,
        )
        return {
            'recipient': recipient_phone,
            'status': 'sent' if ok else 'skipped_no_gateway',
        }
    except Exception as exc:
        logger.error(f'send_sms_task failed: {exc}')
        raise self.retry(exc=exc, countdown=60)


@shared_task(name='iroad.communication.dispatch_event_notification', bind=True, max_retries=3)
def dispatch_event_notification_task(
    self,
    event_code,
    recipient_email=None,
    recipient_phone=None,
    context_dict=None,
    language='en',
    force_django_smtp=False,
):
    """
    Real event dispatcher with fallback in one worker execution.
    This ensures primary failure/timeout can immediately trigger fallback.
    """
    try:
        from superadmin.communication_helpers import dispatch_event_notification

        result = dispatch_event_notification(
            event_code,
            recipient_email=recipient_email,
            recipient_phone=recipient_phone,
            context_dict=context_dict or {},
            language=language,
            force_django_smtp=force_django_smtp,
            use_async_tasks=False,
        )
        return {'event_code': event_code, 'status': 'completed', 'result': bool(result)}
    except Exception as exc:
        logger.error(f'dispatch_event_notification_task failed: {exc}')
        raise self.retry(exc=exc, countdown=30)


@shared_task(name='iroad.communication.dispatch_push', bind=True, max_retries=3)
def dispatch_push_notification_task(self, push_notification_id, context_dict=None):
    """
    Dispatch one push notification via FCM for resolved target tokens.
    """
    try:
        from superadmin.push_helpers import execute_push_notification

        return execute_push_notification(push_notification_id, context_dict=context_dict)
    except Exception as exc:
        logger.error(f'dispatch_push_notification_task failed: {exc}')
        raise self.retry(exc=exc, countdown=60)


@shared_task(name='iroad.communication.archive_old_comm_logs', bind=True, max_retries=3)
def archive_old_comm_logs_task(self, retention_days=90):
    """
    Archive comm logs older than retention_days to cold storage (JSONL) and purge DB.
    """
    try:
        from superadmin.communication_helpers import archive_comm_logs_older_than

        result = archive_comm_logs_older_than(days=int(retention_days))
        logger.info(
            'Archived old comm logs: archived=%s file=%s',
            result.get('archived', 0),
            result.get('file', ''),
        )
        return result
    except Exception as exc:
        logger.error(f'archive_old_comm_logs_task failed: {exc}')
        raise self.retry(exc=exc, countdown=3600)


@shared_task(name='iroad.billing.apply_scheduled_downgrades', bind=True, max_retries=3)
def apply_scheduled_downgrades_task(self):
    """
    Daily: apply plan downgrades scheduled for subscription cycle end (2.3.2.B).
    """
    try:
        from superadmin.billing_helpers import apply_due_scheduled_downgrades

        applied = apply_due_scheduled_downgrades()
        logger.info(f'Applied {applied} scheduled downgrade(s)')
        return {'applied': applied}
    except Exception as exc:
        logger.error(f'apply_scheduled_downgrades_task failed: {exc}')
        raise self.retry(exc=exc, countdown=3600)


@shared_task(name='iroad.billing.check_subscription_expiry', bind=True, max_retries=3)
def check_subscription_expiry_task(self):
    """
    Daily: suspend tenants still Active after subscription_expiry_date + grace.
    """
    try:
        from datetime import date, timedelta

        from superadmin.models import TenantProfile
        from superadmin.billing_helpers import get_subscription_grace_days
        from superadmin.redis_helpers import revoke_all_tenant_sessions

        grace = get_subscription_grace_days()
        cutoff = date.today() - timedelta(days=grace)
        qs = TenantProfile.objects.filter(
            account_status='Active',
            subscription_expiry_date__isnull=False,
            subscription_expiry_date__lt=cutoff,
        )
        suspended = 0
        for tenant in qs.iterator():
            tenant.account_status = 'Suspended_Billing'
            tenant.save(update_fields=['account_status', 'updated_at'])
            revoke_all_tenant_sessions(str(tenant.tenant_id))
            revoke_tenant_sessions_task.delay(str(tenant.tenant_id))
            suspended += 1
        logger.info(
            'Subscription expiry check: cutoff=%s suspended=%s',
            cutoff,
            suspended,
        )
        return {'status': 'completed', 'cutoff': str(cutoff), 'suspended': suspended}
    except Exception as exc:
        logger.error(f'check_subscription_expiry_task failed: {exc}')
        raise self.retry(exc=exc, countdown=3600)


@shared_task(name='iroad.billing.recurring_billing_scan', bind=True, max_retries=3)
def recurring_billing_scan_task(self):
    """
    Periodic billing hygiene: apply scheduled downgrades (same helper as dedicated task).

    Provider-specific recurring card charges remain webhook-driven; this task keeps
    cycle-bound plan transitions moving without manual CP action.
    """
    try:
        from superadmin.billing_helpers import apply_due_scheduled_downgrades

        applied = apply_due_scheduled_downgrades()
        logger.info('recurring_billing_scan: applied %s scheduled downgrade(s)', applied)
        return {'status': 'completed', 'scheduled_downgrades_applied': applied}
    except Exception as exc:
        logger.error(f'recurring_billing_scan_task failed: {exc}')
        raise self.retry(exc=exc, countdown=3600)


@shared_task(name='iroad.billing.proactive_renewal_scan', bind=True, max_retries=3)
def proactive_renewal_scan_task(self):
    """
    Daily scan: Identify subscriptions expiring in 14 days and create draft orders.
    """
    try:
        from superadmin.billing_helpers import scan_active_subscriptions_for_renewal

        generated = scan_active_subscriptions_for_renewal(days_until_expiry=14)
        logger.info('proactive_renewal_scan: generated %s renewal order(s)', generated)
        return {'status': 'completed', 'renewal_orders_generated': generated}
    except Exception as exc:
        logger.error(f'proactive_renewal_scan_task failed: {exc}')
        raise self.retry(exc=exc, countdown=3600)
