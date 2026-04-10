import json
import logging
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.template import Context, Template
from django.utils import timezone

from superadmin.models import (
    CommLog,
    PushDeviceToken,
    PushNotification,
    PushNotificationReceipt,
)

logger = logging.getLogger(__name__)


def _render_text(raw_text, context_dict=None):
    return Template(raw_text or '').render(Context(context_dict or {})).strip()


def _fcm_send(token, title, body, action_link=None):
    server_key = (getattr(settings, 'FCM_SERVER_KEY', '') or '').strip()
    if not server_key:
        raise ValueError('FCM_SERVER_KEY is not configured')

    payload = {
        'to': token,
        'notification': {
            'title': title,
            'body': body,
        },
        'data': {},
        'priority': 'high',
    }
    if action_link:
        payload['data']['action_link'] = action_link

    req = urllib.request.Request(
        getattr(settings, 'FCM_SEND_URL', 'https://fcm.googleapis.com/fcm/send'),
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'key={server_key}',
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status >= 400:
            raise RuntimeError(f'FCM error HTTP {response.status}')
        raw = response.read().decode('utf-8', errors='ignore')
        if '"failure":1' in raw or '"success":0' in raw:
            raise RuntimeError(f'FCM delivery failure: {raw}')
    return True


def _resolve_tokens(push_item):
    qs = PushDeviceToken.objects.filter(is_active=True)

    if push_item.target_audience == 'Tenants':
        qs = qs.filter(user_domain='Tenant_User')
    elif push_item.target_audience == 'Drivers':
        qs = qs.filter(user_domain='Driver')
    elif push_item.target_audience == 'Specific':
        target = (push_item.specific_target_id or '').strip()
        if not target:
            return []
        if ',' in target:
            tokens = [t.strip() for t in target.split(',') if t.strip()]
            return list(
                qs.filter(device_token__in=tokens).values_list('device_token', flat=True)
            ) or tokens
        return list(
            qs.filter(reference_id=target).values_list('device_token', flat=True)
        ) or [target]
    return list(qs.values_list('device_token', flat=True))


def queue_push_notification(push_item):
    from superadmin.tasks import dispatch_push_notification_task

    eta = None
    if push_item.scheduled_at and push_item.scheduled_at > timezone.now():
        eta = push_item.scheduled_at

    if eta:
        dispatch_push_notification_task.apply_async(args=[str(push_item.notification_id)], eta=eta)
        push_item.dispatch_status = 'Scheduled'
    else:
        dispatch_push_notification_task.delay(str(push_item.notification_id))
        push_item.dispatch_status = 'Scheduled'
    push_item.save(update_fields=['dispatch_status'])
    return True


def execute_push_notification(push_notification_id, context_dict=None):
    push_item = PushNotification.objects.get(pk=push_notification_id)
    if push_item.trigger_mode == 'System_Event' and not push_item.is_active:
        return {'status': 'inactive'}

    ctx = context_dict or {}
    title = _render_text(push_item.title_en, ctx)
    body = _render_text(push_item.message_en, ctx)
    event_code = (ctx.get('event_code') or '').strip() or None
    tokens = _resolve_tokens(push_item)

    if not tokens:
        CommLog.objects.create(
            recipient='NO_TARGETS',
            channel_type='Push',
            trigger_source=f'Push: {push_item.internal_name}',
            delivery_status='Failed',
            error_details='No active tokens found for selected audience.',
        )
        return {'status': 'no_targets'}

    sent = 0
    failed = 0
    for token in tokens:
        token_row = PushDeviceToken.objects.filter(device_token=token).first()
        token_domain = (
            token_row.user_domain if token_row else 'Tenant_User'
        )
        token_reference_id = (
            token_row.reference_id if token_row else ''
        )
        token_tenant = token_row.tenant if token_row else None
        try:
            _fcm_send(token, title, body, push_item.action_link)
            CommLog.objects.create(
                recipient=token,
                channel_type='Push',
                trigger_source=f'Push: {push_item.internal_name}',
                delivery_status='Sent',
            )
            PushNotificationReceipt.objects.create(
                tenant=token_tenant,
                notification=push_item,
                device_token=token,
                user_domain=token_domain,
                reference_id=token_reference_id,
                title=title,
                message=body,
                action_link=push_item.action_link,
                event_code=event_code,
                delivery_status='Sent',
            )
            sent += 1
        except Exception as exc:
            CommLog.objects.create(
                recipient=token,
                channel_type='Push',
                trigger_source=f'Push: {push_item.internal_name}',
                delivery_status='Failed',
                error_details=str(exc)[:1000],
            )
            PushNotificationReceipt.objects.create(
                tenant=token_tenant,
                notification=push_item,
                device_token=token,
                user_domain=token_domain,
                reference_id=token_reference_id,
                title=title,
                message=body,
                action_link=push_item.action_link,
                event_code=event_code,
                delivery_status='Failed',
                error_details=str(exc)[:1000],
            )
            failed += 1

    if push_item.dispatch_status != 'Completed':
        push_item.dispatch_status = 'Completed'
        push_item.save(update_fields=['dispatch_status'])
    return {'status': 'completed', 'sent': sent, 'failed': failed}


def dispatch_system_event_pushes(event_code, context_dict=None):
    qs = PushNotification.objects.filter(
        is_active=True,
        trigger_mode='System_Event',
        linked_event=event_code,
    )
    if not qs.exists():
        return 0

    from superadmin.tasks import dispatch_push_notification_task

    count = 0
    for push_item in qs.iterator():
        payload = dict(context_dict or {})
        payload['event_code'] = event_code
        scheduled_at = push_item.scheduled_at
        if scheduled_at and scheduled_at > timezone.now() + timedelta(seconds=5):
            dispatch_push_notification_task.apply_async(
                args=[str(push_item.notification_id), payload],
                eta=scheduled_at,
            )
        else:
            dispatch_push_notification_task.delay(
                str(push_item.notification_id),
                payload,
            )
        count += 1
    return count
