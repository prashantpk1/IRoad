"""
Transactional email/SMS via CP CommGateway and Django's mail layer.

Tenant API bridge secrets (welcome / rotation) always use Django SMTP settings
from ``config/settings.py`` (EMAIL_HOST, EMAIL_PORT, DEFAULT_FROM_EMAIL, etc.),
not the CP Communication → Gateway row, so ops use one production SMTP config.
"""
import logging
import smtplib
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import urllib.request
from base64 import b64encode
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _log_comm_delivery(
    *,
    recipient,
    channel_type,
    trigger_source,
    delivery_status,
    error_details='',
    client_id='',
):
    from superadmin.models import CommLog

    CommLog.objects.create(
        recipient=recipient,
        client_id=(client_id or None),
        channel_type=channel_type,
        trigger_source=trigger_source,
        delivery_status=delivery_status,
        error_details=(error_details or ''),
    )


def get_active_comm_gateway(gateway_type):
    from superadmin.models import CommGateway

    return (
        CommGateway.objects.filter(
            gateway_type=gateway_type,
            is_active=True,
        )
        .order_by('-updated_at')
        .first()
    )


def send_email_smtp_gateway(
    gateway,
    to_email,
    subject,
    text_body,
    html_body=None,
    *,
    trigger_source='Direct: Email',
    client_id=None,
):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = gateway.sender_id
    msg['To'] = to_email
    msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
    if html_body:
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    port = gateway.port
    enc = gateway.encryption_type or 'TLS'
    host = gateway.host_url.strip()
    if port is None:
        port = 465 if enc == 'SSL' else 587

    if enc == 'SSL':
        server = smtplib.SMTP_SSL(host, port, timeout=60)
    else:
        server = smtplib.SMTP(host, port, timeout=60)
        if enc == 'TLS':
            server.starttls()
    try:
        server.login(gateway.username_key, gateway.password_secret)
        server.sendmail(gateway.sender_id, [to_email], msg.as_string())
        _log_comm_delivery(
            recipient=to_email,
            channel_type='Email',
            trigger_source=trigger_source,
            delivery_status='Sent',
            client_id=client_id,
        )
    except Exception as exc:
        _log_comm_delivery(
            recipient=to_email,
            channel_type='Email',
            trigger_source=trigger_source,
            delivery_status='Failed',
            error_details=str(exc)[:1000],
            client_id=client_id,
        )
        raise
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return True


def send_email_via_django_smtp(
    to_email,
    subject,
    text_body,
    html_body=None,
    *,
    trigger_source='Direct: Email',
    client_id=None,
):
    """
    Send using ``EMAIL_BACKEND`` and ``EMAIL_*`` / ``DEFAULT_FROM_EMAIL`` from
    Django settings (``config/settings.py`` + env). Used for security-sensitive
    tenant credential mail so delivery does not depend on CP CommGateway.
    """
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '') or getattr(
        settings,
        'EMAIL_HOST_USER',
        '',
    )
    if not from_email:
        logger.error(
            'Cannot send email: set DEFAULT_FROM_EMAIL or EMAIL_HOST_USER in settings',
        )
        raise ValueError('DEFAULT_FROM_EMAIL (or EMAIL_HOST_USER) is not configured')

    msg = EmailMultiAlternatives(
        subject,
        text_body,
        from_email,
        [to_email],
    )
    if html_body:
        msg.attach_alternative(html_body, 'text/html')
    try:
        msg.send(fail_silently=False)
        _log_comm_delivery(
            recipient=to_email,
            channel_type='Email',
            trigger_source=trigger_source,
            delivery_status='Sent',
            client_id=client_id,
        )
    except Exception as exc:
        _log_comm_delivery(
            recipient=to_email,
            channel_type='Email',
            trigger_source=trigger_source,
            delivery_status='Failed',
            error_details=str(exc)[:1000],
            client_id=client_id,
        )
        raise
    return True


def send_transactional_email(
    to_email,
    subject,
    text_body,
    html_body=None,
    *,
    trigger_source='Direct: Email',
    client_id=None,
):
    """
    Send one email: active CommGateway (Email) if configured, else Django SMTP settings.
    """
    gw = get_active_comm_gateway('Email')
    if gw:
        send_email_smtp_gateway(
            gw,
            to_email,
            subject,
            text_body,
            html_body,
            trigger_source=trigger_source,
            client_id=client_id,
        )
        return True
    return send_email_via_django_smtp(
        to_email,
        subject,
        text_body,
        html_body,
        trigger_source=trigger_source,
        client_id=client_id,
    )


def send_sms_http_gateway(
    gateway,
    recipient_phone,
    message,
    *,
    trigger_source='Direct: SMS',
    client_id=None,
):
    """
    Generic JSON POST to ``gateway.host_url`` for SMS aggregators.

    Payload: {"to": "<phone>", "message": "<text>"}
    Auth: Basic ``username_key`` / ``password_secret`` if both set.
    """
    url = gateway.host_url.strip()
    payload = json.dumps({
        'to': recipient_phone,
        'message': message,
    }).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if gateway.username_key and gateway.password_secret:
        token = b64encode(
            f'{gateway.username_key}:{gateway.password_secret}'.encode('utf-8'),
        ).decode('ascii')
        headers['Authorization'] = f'Basic {token}'
    req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status >= 400:
                raise RuntimeError(f'SMS HTTP {resp.status}')
        _log_comm_delivery(
            recipient=recipient_phone,
            channel_type='SMS',
            trigger_source=trigger_source,
            delivery_status='Sent',
            client_id=client_id,
        )
    except Exception as exc:
        _log_comm_delivery(
            recipient=recipient_phone,
            channel_type='SMS',
            trigger_source=trigger_source,
            delivery_status='Failed',
            error_details=str(exc)[:1000],
            client_id=client_id,
        )
        raise
    return True


def send_transactional_sms(
    recipient_phone,
    message,
    *,
    trigger_source='Direct: SMS',
    client_id=None,
):
    gw = get_active_comm_gateway('SMS')
    if not gw:
        logger.warning('No active SMS gateway; message not sent to %s', recipient_phone)
        _log_comm_delivery(
            recipient=recipient_phone,
            channel_type='SMS',
            trigger_source=trigger_source,
            delivery_status='Failed',
            error_details='No active SMS gateway configured.',
            client_id=client_id,
        )
        return False
    send_sms_http_gateway(
        gw,
        recipient_phone,
        message,
        trigger_source=trigger_source,
        client_id=client_id,
    )
    return True


def _render_template_text(raw_text, context_dict=None):
    """Render DB template text with Django template syntax, e.g. {{company_name}}."""
    return Template(raw_text or '').render(Context(context_dict or {}))


def render_notification_template(template_obj, context_dict=None, language='en'):
    """
    Render subject/body from NotificationTemplate with context replacement.
    """
    lang = (language or 'en').lower()
    use_ar = lang.startswith('ar')

    subject_raw = template_obj.subject_ar if use_ar else template_obj.subject_en
    body_raw = template_obj.body_ar if use_ar else template_obj.body_en

    # Fallback when one language column is empty.
    if not subject_raw:
        subject_raw = template_obj.subject_en or template_obj.subject_ar or ''
    if not body_raw:
        body_raw = template_obj.body_en or template_obj.body_ar or ''

    subject = _render_template_text(subject_raw, context_dict).strip()
    body = _render_template_text(body_raw, context_dict)
    return subject, body


def dispatch_event_notification(
    event_code,
    *,
    recipient_email=None,
    recipient_phone=None,
    context_dict=None,
    language='en',
    force_django_smtp=False,
    use_async_tasks=True,
):
    """
    Generic dispatcher:
    1) resolve active EventMapping by event_code
    2) render mapped template using {{variables}}
    3) send via primary channel, fallback channel on failure
    """
    from superadmin.models import EventMapping

    mapping = (
        EventMapping.objects.select_related('primary_template', 'fallback_template')
        .filter(system_event=event_code, is_active=True)
        .first()
    )
    if not mapping:
        logger.warning('No active event mapping found for %s', event_code)
        return False

    def _send(channel, template_obj):
        subject, body = render_notification_template(template_obj, context_dict, language)
        if channel == 'Email':
            if not recipient_email:
                raise ValueError('recipient_email is required for Email channel')
            if use_async_tasks and not force_django_smtp:
                from superadmin.tasks import send_email_task

                send_email_task.delay(
                    recipient_email,
                    subject or 'Notification',
                    strip_tags(body),
                    str(template_obj.template_id),
                )
                return True
            if force_django_smtp:
                return send_email_via_django_smtp(
                    recipient_email,
                    subject or 'Notification',
                    strip_tags(body),
                    body,
                )
            return send_transactional_email(
                recipient_email,
                subject or 'Notification',
                strip_tags(body),
                body,
                trigger_source=f'Event: {event_code}',
            )
        if channel == 'SMS':
            if not recipient_phone:
                raise ValueError('recipient_phone is required for SMS channel')
            sms_text = strip_tags(body).strip() or body.strip()
            if use_async_tasks:
                from superadmin.tasks import send_sms_task

                send_sms_task.delay(
                    recipient_phone,
                    sms_text,
                    str(template_obj.template_id),
                )
                return True
            return send_transactional_sms(recipient_phone, sms_text)
        raise ValueError(f'Unsupported channel: {channel}')

    result = False
    try:
        result = _send(mapping.primary_channel, mapping.primary_template)
    except Exception as primary_exc:
        logger.exception(
            'Primary notification dispatch failed for %s: %s',
            event_code,
            primary_exc,
        )
        if mapping.fallback_channel and mapping.fallback_template:
            result = _send(mapping.fallback_channel, mapping.fallback_template)
        else:
            raise

    # Keep Push manager linked to the same event-code trigger engine.
    try:
        from superadmin.push_helpers import dispatch_system_event_pushes

        dispatch_system_event_pushes(event_code, context_dict=context_dict)
    except Exception:
        logger.exception('System-event push dispatch failed for %s', event_code)

    # Route internal alerts for this event to configured role/email targets.
    try:
        dispatch_internal_alerts(event_code, context_dict=context_dict)
    except Exception:
        logger.exception('Internal alert routing failed for %s', event_code)
    return result


def dispatch_internal_alerts(event_code, context_dict=None):
    from superadmin.models import AdminUser, InternalAlertRoute
    from superadmin.tasks import send_email_task

    routes = InternalAlertRoute.objects.filter(trigger_event=event_code, is_active=True)
    if not routes.exists():
        return 0

    ctx = context_dict or {}
    subject = f'Internal Alert: {event_code}'
    body = (
        f'Event "{event_code}" triggered.\n\n'
        f'Context:\n{json.dumps(ctx, default=str, ensure_ascii=True)}'
    )
    sent_to = set()
    for route in routes.iterator():
        if route.notify_custom_email:
            email = route.notify_custom_email.strip().lower()
            if email and email not in sent_to:
                send_email_task.delay(email, subject, body, None)
                sent_to.add(email)
        if route.notify_role_id:
            admin_emails = AdminUser.objects.filter(
                role_id=route.notify_role_id,
                status='Active',
            ).values_list('email', flat=True)
            for email in admin_emails:
                norm = (email or '').strip().lower()
                if norm and norm not in sent_to:
                    send_email_task.delay(norm, subject, body, None)
                    sent_to.add(norm)
    return len(sent_to)


def archive_comm_logs_older_than(days=90):
    """
    Archive old CommLog rows to a JSONL file and delete from hot table.
    """
    from superadmin.models import CommLog

    cutoff = timezone.now() - timezone.timedelta(days=days)
    old_qs = CommLog.objects.filter(dispatched_at__lt=cutoff).order_by('dispatched_at')
    if not old_qs.exists():
        return {'archived': 0, 'file': ''}

    archive_dir = Path(getattr(settings, 'MEDIA_ROOT', '.')) / 'comm_logs_archive'
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = timezone.now().strftime('%Y%m%d_%H%M%S')
    archive_file = archive_dir / f'comm_logs_archive_{ts}.jsonl'

    archived = 0
    with archive_file.open('w', encoding='utf-8') as fh:
        for log in old_qs.iterator(chunk_size=1000):
            payload = {
                'log_id': str(log.log_id),
                'recipient': log.recipient,
                'client_id': log.client_id,
                'channel_type': log.channel_type,
                'trigger_source': log.trigger_source,
                'delivery_status': log.delivery_status,
                'error_details': log.error_details,
                'dispatched_at': log.dispatched_at.isoformat() if log.dispatched_at else None,
            }
            fh.write(json.dumps(payload, ensure_ascii=True) + '\n')
            archived += 1

    old_qs.delete()
    return {'archived': archived, 'file': str(archive_file)}


def send_tenant_welcome_email(
    tenant,
    api_bridge_key_plain,
    portal_bootstrap_password_plain=None,
):
    """
    Welcome email after subscriber provisioning (CP-PCS-P1 §4 handover).

    Delivers bridge key and optional initial portal password via email only
    (never shown in Control Panel). SMTP from ``config/settings.py``.
    """
    ctx = {
        'tenant': tenant,
        'api_bridge_key': api_bridge_key_plain,
        'company_name': tenant.company_name,
        'portal_bootstrap_password': portal_bootstrap_password_plain,
        'portal_login_url': (
            getattr(settings, 'TENANT_PORTAL_LOGIN_URL', '') or ''
        ).strip(),
    }
    try:
        sent = dispatch_event_notification(
            'Welcome_Email',
            recipient_email=tenant.primary_email,
            context_dict=ctx,
            language='en',
            # Keep subscriber credential emails on Django SMTP only.
            force_django_smtp=True,
        )
        if sent:
            return True
    except Exception:
        logger.exception(
            'Mapped Welcome_Email dispatch failed; falling back to static template for tenant %s',
            tenant.tenant_id,
        )

    html = render_to_string('tenant/emails/welcome_subscriber.html', ctx)
    text = strip_tags(html)
    subject = f'Welcome to iRoad — {tenant.company_name}'
    return send_email_via_django_smtp(tenant.primary_email, subject, text, html)


def send_tenant_bridge_rotated_email(tenant, api_bridge_key_plain):
    """Notify subscriber that the API bridge key was rotated; plaintext only in email."""
    ctx = {
        'tenant': tenant,
        'api_bridge_key': api_bridge_key_plain,
        'company_name': tenant.company_name,
    }
    html = render_to_string('tenant/emails/api_bridge_rotated.html', ctx)
    text = strip_tags(html)
    subject = f'iRoad — API bridge key rotated — {tenant.company_name}'
    return send_email_via_django_smtp(tenant.primary_email, subject, text, html)
