"""
Transactional email/SMS via CP CommGateway and Django's mail layer.

Tenant API bridge secrets (welcome / rotation) always use Django SMTP settings
from ``config/settings.py`` (EMAIL_HOST, EMAIL_PORT, DEFAULT_FROM_EMAIL, etc.),
not the CP Communication → Gateway row, so ops use one production SMTP config.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import json
import urllib.request
from base64 import b64encode
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


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


def send_email_smtp_gateway(gateway, to_email, subject, text_body, html_body=None):
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
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return True


def send_email_via_django_smtp(to_email, subject, text_body, html_body=None):
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
    msg.send(fail_silently=False)
    return True


def send_transactional_email(to_email, subject, text_body, html_body=None):
    """
    Send one email: active CommGateway (Email) if configured, else Django SMTP settings.
    """
    gw = get_active_comm_gateway('Email')
    if gw:
        send_email_smtp_gateway(gw, to_email, subject, text_body, html_body)
        return True
    return send_email_via_django_smtp(to_email, subject, text_body, html_body)


def send_sms_http_gateway(gateway, recipient_phone, message):
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
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status >= 400:
            raise RuntimeError(f'SMS HTTP {resp.status}')
    return True


def send_transactional_sms(recipient_phone, message):
    gw = get_active_comm_gateway('SMS')
    if not gw:
        logger.warning('No active SMS gateway; message not sent to %s', recipient_phone)
        return False
    send_sms_http_gateway(gw, recipient_phone, message)
    return True


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
