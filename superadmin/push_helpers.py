import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.utils import timezone
from firebase_admin import credentials, get_app, initialize_app, messaging

from superadmin.models import (
    CommLog,
    PushDeviceToken,
    PushNotification,
    PushNotificationReceipt,
)

logger = logging.getLogger(__name__)


def _render_text(raw_text, context_dict=None):
    return Template(raw_text or '').render(Context(context_dict or {})).strip()


def _firebase_app():
    app_name = (getattr(settings, 'FIREBASE_APP_NAME', '') or 'iroad-fcm').strip()
    try:
        return get_app(app_name)
    except ValueError:
        service_account_file = (
            getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_FILE', '') or ''
        ).strip()
        if not service_account_file:
            raise ValueError('FIREBASE_SERVICE_ACCOUNT_FILE is not configured')

        service_account_path = Path(service_account_file)
        if not service_account_path.exists():
            raise FileNotFoundError(
                f'Firebase service account file not found: {service_account_file}'
            )
        cred = credentials.Certificate(str(service_account_path))
        return initialize_app(cred, name=app_name)


def _fcm_send(token, title, body, action_link=None, device_type=None):
    app = _firebase_app()
    data_payload = {}
    if action_link:
        data_payload['action_link'] = str(action_link)

    message_kwargs = {
        'token': token,
        'notification': messaging.Notification(title=title, body=body),
        'data': data_payload,
        'android': messaging.AndroidConfig(priority='high'),
    }
    # device_type: 0=iOS, 1=Android
    if device_type == 0:
        message_kwargs['apns'] = messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound='default'),
            ),
        )

    message = messaging.Message(**message_kwargs)
    messaging.send(message, app=app)
    return True


def _resolve_tokens(push_item):
    qs = PushDeviceToken.objects.filter(is_active=True)

    if push_item.target_audience == 'Tenants':
        qs = qs.filter(user_domain='Tenant_User')
    elif push_item.target_audience == 'Drivers':
        qs = qs.filter(user_domain='Driver')
        tokens = list(qs.values_list('device_token', flat=True))
        # Optional override: paste raw FCM token(s) in specific_target_id
        # when no driver has logged in with fcm_token yet (local testing).
        override = (push_item.specific_target_id or '').strip()
        if override:
            extra = [t.strip() for t in override.split(',') if t.strip()]
            for t in extra:
                if t not in tokens:
                    tokens.append(t)
        return tokens
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
    from superadmin.push_debug_log import append_push_debug

    eta = None
    if push_item.scheduled_at and push_item.scheduled_at > timezone.now():
        eta = push_item.scheduled_at

    push_item.dispatch_status = 'Scheduled'
    push_item.save(update_fields=['dispatch_status'])

    # Log first so time.txt always shows queue attempt even if Celery fails.
    append_push_debug(
        f'PUSH_QUEUE {"eta=" + str(eta) if eta else "immediate"} '
        f'name={push_item.internal_name!r} audience={push_item.target_audience} '
        f'id={push_item.notification_id}'
    )

    # Immediate (no future ETA): always send in this request.
    # Celery worker is often not running locally; this guarantees time.txt
    # gets PUSH_SEND lines. Future ETA still uses Celery.
    if not eta:
        append_push_debug('PUSH_QUEUE mode=sync_immediate')
        execute_push_notification(str(push_item.notification_id))
        return True

    try:
        dispatch_push_notification_task.apply_async(
            args=[str(push_item.notification_id)],
            eta=eta,
        )
        append_push_debug('PUSH_QUEUE celery_accepted eta')
    except Exception as exc:
        append_push_debug(f'PUSH_QUEUE CELERY_FAIL {exc!r} — falling back to sync send')
        execute_push_notification(str(push_item.notification_id))
    return True


def execute_push_notification(push_notification_id, context_dict=None):
    from superadmin.push_debug_log import append_push_debug

    push_item = PushNotification.objects.get(pk=push_notification_id)
    if push_item.trigger_mode == 'System_Event' and not push_item.is_active:
        append_push_debug(
            f'PUSH_SEND SKIP inactive System_Event name={push_item.internal_name!r}'
        )
        return {'status': 'inactive'}

    ctx = context_dict or {}
    title = _render_text(push_item.title_en, ctx)
    body = _render_text(push_item.message_en, ctx)
    event_code = (ctx.get('event_code') or '').strip() or None
    tokens = _resolve_tokens(push_item)

    if not tokens:
        active_drivers = PushDeviceToken.objects.filter(
            is_active=True, user_domain='Driver'
        ).count()
        active_all = PushDeviceToken.objects.filter(is_active=True).count()
        CommLog.objects.create(
            recipient='NO_TARGETS',
            channel_type='Push',
            trigger_source=f'Push: {push_item.internal_name}',
            delivery_status='Failed',
            error_details=(
                'No active tokens found for selected audience. '
                f'audience={push_item.target_audience} '
                f'active_driver_tokens={active_drivers} active_all_tokens={active_all}. '
                'Drivers Only needs a prior mobile login with fcm_token.'
            ),
        )
        append_push_debug(
            f'PUSH_SEND FAIL no_targets name={push_item.internal_name!r} '
            f'audience={push_item.target_audience} '
            f'active_driver_tokens={active_drivers} active_all_tokens={active_all} '
            f'reason=no_FCM_token_in_DB_login_with_fcm_token_first'
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
            _fcm_send(
                token,
                title,
                body,
                push_item.action_link,
                device_type=getattr(token_row, 'device_type', None) if token_row else None,
            )
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
            preview = (token[:24] + '...') if len(token) > 24 else token
            append_push_debug(
                f'PUSH_SEND OK name={push_item.internal_name!r} '
                f'domain={token_domain} '
                f'device_type={getattr(token_row, "device_type", None)} '
                f'token_preview={preview!r}'
            )
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
            append_push_debug(
                f'PUSH_SEND FAIL name={push_item.internal_name!r} '
                f'error={str(exc)[:300]}'
            )

    if push_item.dispatch_status != 'Completed':
        push_item.dispatch_status = 'Completed'
        push_item.save(update_fields=['dispatch_status'])
    append_push_debug(
        f'PUSH_SEND DONE name={push_item.internal_name!r} sent={sent} failed={failed}'
    )
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
