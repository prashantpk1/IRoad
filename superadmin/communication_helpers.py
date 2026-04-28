"""
Transactional email/SMS via CP CommGateway and Django's mail layer.

Tenant API bridge secrets (welcome / rotation) always use Django SMTP settings
from ``config/settings.py`` (EMAIL_HOST, EMAIL_PORT, DEFAULT_FROM_EMAIL, etc.),
not the CP Communication → Gateway row, so ops use one production SMTP config.
"""
import os
import logging
import smtplib
import json
from decouple import config
from email.utils import formataddr, parseaddr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import urllib.request
import urllib.parse
from base64 import b64encode
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _get_base_url():
    """
    Attempt to resolve the base URL of the site.
    Prefer 'SITE_URL' setting, then 'TENANT_PORTAL_LOGIN_URL' (stripped),
    with a final fallback to localhost.
    """
    site_url = getattr(settings, 'SITE_URL', config('SITE_URL', default='')).strip()
    if site_url:
        return site_url.rstrip('/')

    # Check for another common setting
    portal_url = getattr(settings, 'TENANT_PORTAL_LOGIN_URL', '').strip()
    if portal_url:
        # If it's a full URL, use its origin
        if '://' in portal_url:
            from urllib.parse import urlparse
            p = urlparse(portal_url)
            return f"{p.scheme}://{p.netloc}"

    return 'http://127.0.0.1:8000'


def _build_branding_context():
    """
    Resolve branding values from Legal Identity for email wrappers.
    Falls back to default IR/iRoad when no logo/name configured.
    Ensures brand_logo_url is absolute for external email clients.
    """
    brand_name = 'iRoad'
    brand_name_ar = 'iRoad'
    # Default fallback image
    brand_logo_url = '/media/legal/Link.png'
    brand_initials = 'IR'
    
    brand_company_name_ar = brand_name_ar

    try:
        from superadmin.models import LegalIdentity

        legal = LegalIdentity.objects.filter(
            identity_id='GLOBAL-LEGAL-IDENTITY',
        ).first()
        if legal:
            if (legal.company_name_en or '').strip():
                brand_name = legal.company_name_en.strip()
            if (legal.company_name_ar or '').strip():
                brand_name_ar = legal.company_name_ar.strip()

            if getattr(legal, 'company_logo', None):
                try:
                    brand_logo_url = legal.company_logo.url or brand_logo_url
                except Exception:
                    pass

            letters = ''.join(ch for ch in brand_name if ch.isalnum()).upper()
            if letters:
                brand_initials = letters[:2]
    except Exception:
        pass

    # Standardize logo URL resolution (ensure absolute URL)
    if brand_logo_url:
        if not (brand_logo_url.startswith('http') or brand_logo_url.startswith('//')):
            base = _get_base_url()
            if not brand_logo_url.startswith('/'):
                brand_logo_url = f"/{brand_logo_url}"
            brand_logo_url = f"{base}{brand_logo_url}"

    return {
        'brand_company_name': brand_name,
        'brand_company_name_ar': brand_name_ar,
        'brand_logo_url': brand_logo_url,
        'brand_initials': brand_initials,
        'brand_support_email': '',
        'brand_support_phone': '',
        'brand_registered_address': '',
        'brand_tax_number': '',
    }


def _merge_template_context(context_dict=None):
    merged = _build_branding_context()
    if context_dict:
        merged.update(context_dict)
    return merged


def _resolve_safe_from_email(preferred_from=''):
    """
    Ensure SMTP sender aligns with authenticated account for Gmail providers.
    Prevents SMTPSenderRefused when placeholder/default sender is configured.
    """
    fallback_user = (getattr(settings, 'FALLBACK_EMAIL_HOST_USER', '') or '').strip()
    candidate = (preferred_from or '').strip()
    if not fallback_user:
        return candidate
    lower_candidate = candidate.lower()
    if (not candidate) or ('your-email@gmail.com' in lower_candidate):
        return fallback_user
    return candidate


def _normalize_from_email_header(raw_from='', fallback_email=''):
    """
    Return a stable RFC-2822 From header with a consistent display name.
    """
    fallback = (fallback_email or '').strip()
    display_name = (
        getattr(settings, 'EMAIL_FROM_DISPLAY_NAME', 'Iroad Platform')
        or 'Iroad Platform'
    ).strip()

    name, addr = parseaddr((raw_from or '').strip())
    if not addr:
        addr = fallback
    if not addr:
        return ''
    if name:
        return formataddr((name, addr))
    return formataddr((display_name, addr))


def _extract_sender_address(raw_from='', fallback_email=''):
    """
    Extract SMTP envelope sender address from a header-like value.
    """
    _name, addr = parseaddr((raw_from or '').strip())
    if addr:
        return addr
    return (fallback_email or '').strip()


def _send_via_fallback_smtp(to_email, subject, text_body, html_body=None):
    fallback_user = (getattr(settings, 'FALLBACK_EMAIL_HOST_USER', '') or '').strip()
    fallback_pass = (getattr(settings, 'FALLBACK_EMAIL_HOST_PASSWORD', '') or '').strip()
    if not fallback_user or not fallback_pass:
        raise ValueError('Fallback SMTP credentials are not configured')

    host = getattr(settings, 'FALLBACK_EMAIL_HOST', 'smtp.gmail.com')
    port = int(getattr(settings, 'FALLBACK_EMAIL_PORT', 587))
    use_ssl = bool(getattr(settings, 'FALLBACK_EMAIL_USE_SSL', False))
    use_tls = bool(getattr(settings, 'FALLBACK_EMAIL_USE_TLS', True))
    sender_raw = _resolve_safe_from_email(
        getattr(settings, 'DEFAULT_FROM_EMAIL', '') or fallback_user,
    )
    sender = _normalize_from_email_header(sender_raw, fallback_user)
    envelope_from = _extract_sender_address(sender, fallback_user)

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to_email
    msg.attach(MIMEText(text_body or '', 'plain', 'utf-8'))
    if html_body:
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=60)
    else:
        server = smtplib.SMTP(host, port, timeout=60)
        if use_tls:
            server.starttls()
    try:
        server.login(fallback_user, fallback_pass)
        server.sendmail(envelope_from, [to_email], msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Reusable HTML email fragments – header / footer / wrapper
# ---------------------------------------------------------------------------
_EMAIL_HEADER = (
    '<div style="background:linear-gradient(135deg,#4f46e5 0%,#6366f1 50%,#818cf8 100%);'
    'padding:36px 40px 32px;text-align:center;border-radius:16px 16px 0 0;">'
    '<h1 style="color:#fff;margin:0;font-size:26px;font-weight:800;'
    'letter-spacing:-0.03em;font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif;">'
    'iRoad</h1>'
    '<p style="color:rgba(255,255,255,.75);font-size:13px;font-weight:500;'
    'margin:6px 0 0;letter-spacing:0.02em;font-family:Inter,sans-serif;">'
    'Logistics Management Platform</p>'
    '</div>'
    '<div style="height:4px;background:linear-gradient(90deg,#f59e0b 0%,#fbbf24 35%,'
    '#34d399 65%,#10b981 100%);"></div>'
)

_EMAIL_FOOTER = (
    '<div style="background:#f8fafc;border-top:1px solid #e2e8f0;'
    'padding:28px 44px 32px;text-align:center;border-radius:0 0 16px 16px;">'
    '<p style="font-size:16px;font-weight:800;color:#4f46e5;'
    'letter-spacing:-0.02em;margin:0 0 8px;font-family:Inter,sans-serif;">iRoad</p>'
    '<p style="font-size:12px;color:#94a3b8;line-height:1.8;margin:0;'
    'font-family:Inter,sans-serif;">'
    '&copy; 2026 iRoad Logistics. All rights reserved.<br>'
    'This is an automated system notification. Please do not reply.</p>'
    '<div style="margin:14px 0 0;">'
    '<span style="display:inline-block;background:linear-gradient(135deg,#4f46e5,#6366f1);'
    'color:#fff;font-size:10px;font-weight:700;padding:4px 12px;border-radius:20px;'
    'letter-spacing:0.05em;text-transform:uppercase;">Secured &amp; Encrypted</span>'
    '</div>'
    '</div>'
)

def _wrap_email_body(inner_html, email_title="Notification", preheader="Secure notification from iRoad", use_rtl=False):
    base_html = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>{{ brand_company_name|default:"iRoad Logistics" }}</title>
    <!--[if mso]>
    <noscript>
        <xml>
            <o:OfficeDocumentSettings>
                <o:PixelsPerInch>96</o:PixelsPerInch>
            </o:OfficeDocumentSettings>
        </xml>
    </noscript>
    <![endif]-->
    <style>
        /* Reset */
        body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
        table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
        img { -ms-interpolation-mode: bicubic; border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; }
        body { margin: 0 !important; padding: 0 !important; width: 100% !important; font-family: 'Inter', -apple-system, sans-serif; background-color: #f1f5f9; }

        /* Wrapper */
        .email-wrapper {
            width: 100%;
            max-width: 640px;
            margin: 40px auto;
            background: #ffffff;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04);
        }

        /* Header */
        .email-header {
            background: linear-gradient(135deg, #4f46e5 0%, #6366f1 50%, #818cf8 100%);
            padding: 36px 40px 32px;
            text-align: center;
        }
        .email-logo-box {
            width: 52px;
            height: 52px;
            line-height: 52px;
            margin: 0 auto 14px;
            border-radius: 14px;
            background: rgba(255, 255, 255, 0.2);
            color: #ffffff;
            font-size: 20px;
            font-weight: 800;
            overflow: hidden;
            border: 2px solid rgba(255, 255, 255, 0.3);
        }
        .email-logo-img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .email-brand {
            color: #ffffff;
            margin: 0;
            font-size: 26px;
            font-weight: 800;
            letter-spacing: -0.03em;
            line-height: 1.2;
        }
        .email-brand-sub {
            color: rgba(255, 255, 255, 0.75);
            font-size: 13px;
            font-weight: 500;
            margin: 6px 0 0;
            letter-spacing: 0.02em;
        }
        .header-divider {
            height: 4px;
            background: linear-gradient(90deg, #f59e0b 0%, #fbbf24 35%, #34d399 65%, #10b981 100%);
        }

        /* Body */
        .email-body {
            padding: 40px 44px;
        }
        .email-body h2 {
            color: #1e293b;
            margin: 0 0 16px;
            font-size: 22px;
            font-weight: 700;
            letter-spacing: -0.02em;
        }
        .email-body p {
            margin: 0 0 16px;
            font-size: 15px;
            color: #475569;
            line-height: 1.7;
        }
        
        /* Footer */
        .email-footer {
            background: #f8fafc;
            border-top: 1px solid #e2e8f0;
            padding: 28px 44px 32px;
            text-align: center;
        }
        .footer-logo-text {
            font-size: 16px;
            font-weight: 800;
            color: #4f46e5;
            letter-spacing: -0.02em;
            margin-bottom: 8px;
        }
        .footer-text {
            font-size: 12px;
            color: #94a3b8;
            line-height: 1.8;
            margin: 0;
        }
        .footer-badge {
            display: inline-block;
            background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
            color: #ffffff;
            font-size: 10px;
            font-weight: 700;
            padding: 4px 12px;
            border-radius: 20px;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-top: 14px;
        }

        /* RTL support */
        .rtl { direction: rtl; text-align: right; }
    </style>
</head>
<body>
    <div style="display: none; font-size: 1px; color: #f1f5f9; line-height: 1px; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden;">
        """ + preheader + r"""
    </div>

    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
        <tr>
            <td align="center" style="padding: 0 16px;">
                <div class="email-wrapper">
                    <div class="email-header">
                        <div class="email-logo-box">
                            {% if brand_logo_url %}
                                <img src="{{ brand_logo_url }}" class="email-logo-img" alt="{{ brand_company_name }}">
                            {% else %}
                                {{ brand_initials|default:"IR" }}
                            {% endif %}
                        </div>
                        <h1 class="email-brand">{{ brand_company_name|default:"iRoad" }}</h1>
                        <p class="email-brand-sub">Logistics Management Platform</p>
                    </div>
                    <div class="header-divider"></div>

                    <div class="email-body """ + ("rtl" if use_rtl else "") + r"""">
                        """ + inner_html + r"""
                    </div>

                    <div class="email-footer">
                        <div class="footer-logo-text">{{ brand_company_name|default:"iRoad" }}</div>
                        <p class="footer-text">
                            &copy; 2026 {{ brand_company_name|default:"iRoad Logistics" }}. All rights reserved.<br>
                            This is an automated system notification. Please do not reply.
                        </p>
                        <div class="footer-badge">Secured &amp; Encrypted</div>
                    </div>
                </div>
            </td>
        </tr>
    </table>
</body>
</html>
"""
    return base_html

DEFAULT_NOTIFICATION_EMAIL_TEMPLATES = [
    {
        'template_name': 'AUTH_LOGIN_OTP',
        'category': 'Transactional',
        'subject_en': 'Your iRoad Login Verification Code',
        'subject_ar': 'رمز التحقق لتسجيل الدخول إلى iRoad',
        'body_en': (
            '<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f1f5f9;">'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="background:#f1f5f9;padding:24px 12px;"><tr><td align="center">'
            '<table role="presentation" width="640" cellspacing="0" cellpadding="0" border="0" '
            'style="width:640px;max-width:640px;background:#ffffff;border-radius:16px;overflow:hidden;">'
            '<tr><td style="background:linear-gradient(135deg,#4f46e5 0%,#6366f1 50%,#818cf8 100%);padding:28px 24px;text-align:center;">'
            '<div style="width:52px;height:52px;line-height:52px;margin:0 auto 12px;border-radius:14px;'
            'background:rgba(255,255,255,0.2);color:#ffffff;font-size:20px;font-weight:800;'
            'overflow:hidden;border:2px solid rgba(255,255,255,0.3);">'
            '{% if brand_logo_url %}'
            '<img src="{{ brand_logo_url }}" style="width:100%;height:100%;object-fit:cover;" alt="{{ brand_company_name }}">'
            '{% else %}'
            '{{ brand_initials|default:"IR" }}'
            '{% endif %}'
            '</div>'
            '<div style="color:#ffffff;font-size:26px;line-height:1.2;font-weight:800;letter-spacing:-0.02em;font-family:Arial,sans-serif;">'
            '{{ brand_company_name|default:"iRoad" }}</div>'
            '<div style="color:rgba(255,255,255,0.7);font-size:13px;line-height:1.5;font-weight:500;'
            'font-family:Arial,sans-serif;margin-top:4px;">Logistics Management Platform</div>'
            '</td></tr>'
            '<tr><td style="padding:34px 34px 28px;font-family:Arial,sans-serif;color:#1f2d3d;">'
            '<h2 style="margin:0 0 16px;font-size:34px;line-height:1.2;font-weight:700;color:#102a56;">'
            'OTP Verification Required 🔐</h2>'
            '<p style="margin:0 0 16px;font-size:24px;line-height:1.6;color:#334e68;">'
            'Hello {{ user_name|default:"Admin" }},</p>'
            '<p style="margin:0 0 20px;font-size:24px;line-height:1.6;color:#334e68;">'
            'Use the following one-time verification code to complete your iRoad login:</p>'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="background:#dfe4f6;border:1px solid #b4c2f0;border-radius:14px;padding:16px 14px;">'
            '<tr><td style="font-size:12px;font-weight:700;letter-spacing:1px;color:#4b4cd6;'
            'text-transform:uppercase;padding-bottom:10px;font-family:Arial,sans-serif;">One-Time Password</td></tr>'
            '<tr><td align="center" style="padding:6px 0 8px;">'
            '<div style="display:inline-block;background:#1f2d49;color:#ffffff;border-radius:12px;'
            'padding:14px 26px;font-family:Courier New,monospace;font-size:42px;letter-spacing:8px;'
            'font-weight:700;">{{ otp_code|default:otp }}</div>'
            '</td></tr>'
            '<tr><td align="center" style="font-size:14px;color:#334e68;font-family:Arial,sans-serif;">'
            'Valid for <strong>5 minutes</strong> only.</td></tr></table>'
            '<p style="margin:18px 0 0;font-size:18px;line-height:1.7;color:#334e68;">'
            'Do not share this code with anyone, including iRoad support staff.</p>'
            '<hr style="border:none;border-top:1px solid #d9e2ec;margin:20px 0;">'
            '<p style="margin:0;font-size:16px;line-height:1.7;color:#829ab1;">'
            'If you did not attempt to sign in, please contact your administrator immediately.</p>'
            '</td></tr>'
            '<tr><td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:24px;text-align:center;'
            'font-family:Arial,sans-serif;">'
            '<div style="font-size:24px;font-weight:700;color:#4b4cd6;margin-bottom:8px;">iRoad</div>'
            '<div style="font-size:13px;line-height:1.7;color:#829ab1;">'
            '&copy; 2026 iRoad Logistics. All rights reserved.<br>'
            'This is an automated system notification. Please do not reply to this email.</div>'
            '<div style="font-size:13px;color:#4b4cd6;margin-top:12px;">Privacy Policy &nbsp; · &nbsp; Terms of Service &nbsp; · &nbsp; Support</div>'
            '<div style="display:inline-block;margin-top:12px;background:#5b5ce2;color:#ffffff;'
            'border-radius:18px;padding:6px 14px;font-size:11px;font-weight:700;letter-spacing:0.5px;">'
            'SECURED &amp; ENCRYPTED</div>'
            '</td></tr></table></td></tr></table></body></html>'
        ),
        'body_ar': (
            '<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f1f5f9;">'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="background:#f1f5f9;padding:24px 12px;"><tr><td align="center">'
            '<table role="presentation" width="640" cellspacing="0" cellpadding="0" border="0" '
            'style="width:640px;max-width:640px;background:#ffffff;border-radius:16px;overflow:hidden;">'
            '<tr><td style="background:linear-gradient(135deg,#4f46e5 0%,#6366f1 50%,#818cf8 100%);padding:28px 24px;text-align:center;">'
            '<div style="width:52px;height:52px;line-height:52px;margin:0 auto 12px;border-radius:14px;'
            'background:rgba(255,255,255,0.2);color:#ffffff;font-size:20px;font-weight:800;'
            'overflow:hidden;border:2px solid rgba(255,255,255,0.3);">'
            '{% if brand_logo_url %}'
            '<img src="{{ brand_logo_url }}" style="width:100%;height:100%;object-fit:cover;" alt="{{ brand_company_name }}">'
            '{% else %}'
            '{{ brand_initials|default:"IR" }}'
            '{% endif %}'
            '</div>'
            '<div style="color:#ffffff;font-size:26px;line-height:1.2;font-weight:800;letter-spacing:-0.02em;font-family:Arial,sans-serif;">'
            '{{ brand_company_name|default:"iRoad" }}</div>'
            '<div style="color:rgba(255,255,255,0.7);font-size:13px;line-height:1.5;font-weight:500;'
            'font-family:Arial,sans-serif;margin-top:4px;">منصة إدارة الخدمات اللوجستية</div>'
            '</td></tr>'
            '<tr><td style="padding:34px 34px 28px;font-family:Arial,sans-serif;color:#1f2d3d;" dir="rtl">'
            '<h2 style="margin:0 0 16px;font-size:34px;line-height:1.2;font-weight:700;color:#102a56;">'
            'مطلوب التحقق برمز OTP 🔐</h2>'
            '<p style="margin:0 0 16px;font-size:24px;line-height:1.6;color:#334e68;">'
            'مرحباً {{ user_name|default:"Admin" }}،</p>'
            '<p style="margin:0 0 20px;font-size:24px;line-height:1.6;color:#334e68;">'
            'استخدم رمز التحقق التالي لإكمال تسجيل الدخول إلى iRoad:</p>'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="background:#dfe4f6;border:1px solid #b4c2f0;border-radius:14px;padding:16px 14px;">'
            '<tr><td style="font-size:12px;font-weight:700;letter-spacing:1px;color:#4b4cd6;'
            'text-transform:uppercase;padding-bottom:10px;font-family:Arial,sans-serif;">رمز التحقق لمرة واحدة</td></tr>'
            '<tr><td align="center" style="padding:6px 0 8px;">'
            '<div style="display:inline-block;background:#1f2d49;color:#ffffff;border-radius:12px;'
            'padding:14px 26px;font-family:Courier New,monospace;font-size:42px;letter-spacing:8px;'
            'font-weight:700;">{{ otp_code|default:otp }}</div>'
            '</td></tr>'
            '<tr><td align="center" style="font-size:14px;color:#334e68;font-family:Arial,sans-serif;">'
            'صالح لمدة <strong>5 دقائق</strong> فقط.</td></tr></table>'
            '<p style="margin:18px 0 0;font-size:18px;line-height:1.7;color:#334e68;">'
            'لا تشارك هذا الرمز مع أي شخص، بما في ذلك فريق دعم iRoad.</p>'
            '<hr style="border:none;border-top:1px solid #d9e2ec;margin:20px 0;">'
            '<p style="margin:0;font-size:16px;line-height:1.7;color:#829ab1;">'
            'إذا لم تحاول تسجيل الدخول، يرجى التواصل مع المسؤول فوراً.</p>'
            '</td></tr>'
            '<tr><td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:24px;text-align:center;'
            'font-family:Arial,sans-serif;">'
            '<div style="font-size:24px;font-weight:700;color:#4b4cd6;margin-bottom:8px;">iRoad</div>'
            '<div style="font-size:13px;line-height:1.7;color:#829ab1;">'
            '&copy; 2026 iRoad Logistics. All rights reserved.<br>'
            'هذه رسالة نظام آلية، يرجى عدم الرد على هذا البريد.</div>'
            '<div style="font-size:13px;color:#4b4cd6;margin-top:12px;">الخصوصية &nbsp; · &nbsp; الشروط &nbsp; · &nbsp; الدعم</div>'
            '<div style="display:inline-block;margin-top:12px;background:#5b5ce2;color:#ffffff;'
            'border-radius:18px;padding:6px 14px;font-size:11px;font-weight:700;letter-spacing:0.5px;">'
            'مؤمَّن ومشفَّر</div>'
            '</td></tr></table></td></tr></table></body></html>'
        ),
    },
    {
        'template_name': 'AUTH_PASSWORD_RESET',
        'category': 'Transactional',
        'subject_en': 'Reset Your iRoad Password',
        'subject_ar': 'إعادة تعيين كلمة مرور iRoad',
        'body_en': _wrap_email_body(
            '<h2>Reset Your Password 🔐</h2>'
            '<p>Hello {{ admin_user.first_name|default:"Admin" }},</p>'
            '<p>We received a request to reset the password for your iRoad admin account. '
            'Click the button below to set a new password:</p>'
            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ reset_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">Reset Password &rarr;</a>'
            '</div>'
            '<div style="height:1px;background:#e2e8f0;margin:28px 0;"></div>'
            '<p style="font-size:13px;color:#94a3b8;line-height:1.6;">'
            'If you did not request this password reset, you can safely ignore this email. '
            'Your password will not be changed.</p>'
        ),
        'body_ar': _wrap_email_body(
            '<div dir="rtl" style="text-align:right;">'
            '<h2>إعادة تعيين كلمة المرور 🔐</h2>'
            '<p>مرحباً {{ admin_user.first_name|default:"Admin" }}،</p>'
            '<p>تلقينا طلباً لإعادة تعيين كلمة المرور لحسابك في iRoad. '
            'اضغط الزر أدناه لتعيين كلمة مرور جديدة:</p>'
            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ reset_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">إعادة تعيين كلمة المرور &larr;</a>'
            '</div>'
            '<div style="height:1px;background:#e2e8f0;margin:28px 0;"></div>'
            '<p style="font-size:13px;color:#94a3b8;line-height:1.6;">'
            'إذا لم تطلب ذلك، يمكنك تجاهل هذه الرسالة. لن يتم تغيير كلمة المرور.</p>'
            '</div>'
        ),
    },
    {
        'template_name': 'AUTH_ADMIN_INVITE',
        'category': 'Transactional',
        'subject_en': 'Activate Your iRoad Admin Account',
        'subject_ar': 'تفعيل حساب مدير iRoad',
        'body_en': _wrap_email_body(
            '<h2>You\'re Invited! 🎉</h2>'
            '<p>Hello {{ admin_user.first_name|default:"Admin" }},</p>'
            '<p>You have been invited to join the <strong>iRoad</strong> admin panel. '
            'Click the button below to activate your account and set up your credentials:</p>'
            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ invite_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">Activate Account &rarr;</a>'
            '</div>'
            '<div style="height:1px;background:#e2e8f0;margin:28px 0;"></div>'
            '<p style="font-size:13px;color:#94a3b8;line-height:1.6;">'
            'If you did not expect this invitation, please contact your system administrator.</p>'
        ),
        'body_ar': _wrap_email_body(
            '<div dir="rtl" style="text-align:right;">'
            '<h2>لقد تمت دعوتك! 🎉</h2>'
            '<p>مرحباً {{ admin_user.first_name|default:"Admin" }}،</p>'
            '<p>تمت دعوتك للانضمام إلى لوحة تحكم <strong>iRoad</strong>. '
            'اضغط الزر أدناه لتفعيل حسابك وإعداد بيانات الدخول:</p>'
            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ invite_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">تفعيل الحساب &larr;</a>'
            '</div>'
            '<div style="height:1px;background:#e2e8f0;margin:28px 0;"></div>'
            '<p style="font-size:13px;color:#94a3b8;line-height:1.6;">'
            'إذا لم تكن تتوقع هذه الدعوة، يرجى التواصل مع مدير النظام.</p>'
            '</div>'
        ),
    },
    {
        'template_name': 'TENANT_WELCOME_EMAIL',
        'category': 'Transactional',
        'subject_en': 'Welcome to iRoad — {{ company_name }}',
        'subject_ar': 'مرحباً بك في iRoad — {{ company_name }}',
        'body_en': _wrap_email_body(
            '<h2>Welcome, {{ company_name }}! 🚀</h2>'
            '<p>Your subscriber workspace has been provisioned and is ready for setup. '
            'Below are your sign-in credentials.</p>'
            
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="font-size:11px;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.06em;color:#6366f1;margin:0 0 6px;">Portal Access</p>'
            '<p style="margin:8px 0 4px;font-size:14px;color:#334155;">'
            '<strong>Login email:</strong> {{ tenant.primary_email }}</p>'
            '</div>'

            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ invite_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">Complete Account Setup &rarr;</a>'
            '</div>'
        ),
        'body_ar': _wrap_email_body(
            '<div dir="rtl" style="text-align:right;">'
            '<h2>مرحباً بك في iRoad، {{ company_name }}! 🚀</h2>'
            '<p>تم تجهيز مساحة العمل الخاصة بك وهي جاهزة للإعداد الآن. أدناه تفاصيل الوصول الخاصة بك.</p>'
            
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="font-size:11px;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.06em;color:#6366f1;margin:0 0 6px;">بيانات الوصول للبوابة</p>'
            '<p style="margin:8px 0 4px;font-size:14px;color:#334155;">'
            '<strong>البريد الإلكتروني:</strong> {{ tenant.primary_email }}</p>'
            '</div>'

            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ invite_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">إكمال إعداد الحساب &larr;</a>'
            '</div>'
            '</div>',
            use_rtl=True
        ),
    },
    {
        'template_name': 'SUBADMIN_WELCOME',
        'category': 'Transactional',
        'subject_en': 'Welcome to iRoad - Your Admin Credentials',
        'subject_ar': 'مرحباً بك في iRoad - بيانات الدخول الخاصة بك',
        'body_en': _wrap_email_body(
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'Welcome, {{ name }}! 🎉</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 16px;">'
            'Your iRoad admin account has been created successfully. Below are your login credentials '
            'to access the Control Panel.</p>'
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="margin:0 0 8px;font-size:14px;color:#334155;">'
            '<strong>Login Email:</strong> {{ email }}</p>'
            '<p style="margin:0;font-size:14px;color:#334155;">'
            '<strong>Temporary Password:</strong></p>'
            '<div style="background:#1e293b;color:#e2e8f0;padding:12px 16px;border-radius:8px;'
            'font-family:monospace;font-size:14px;margin-top:8px;'
            'border:1px solid #334155;">{{ password }}</div>'
            '</div>'
            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ login_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">Access Control Panel &rarr;</a>'
            '</div>'
            '<p style="font-size:13px;color:#94a3b8;">'
            'Please change your password immediately after your first login for security reasons.</p>'
        ),
        'body_ar': _wrap_email_body(
            '<div dir="rtl" style="text-align:right;">'
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'مرحباً بك، {{ name }}! 🎉</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 16px;">'
            'تم إنشاء حساب المسؤول الخاص بك بنجاح في iRoad. فيما يلي بيانات الدخول الخاصة بك للوصول إلى لوحة التحكم.</p>'
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="margin:0 0 8px;font-size:14px;color:#334155;">'
            '<strong>البريد الإلكتروني:</strong> {{ email }}</p>'
            '<p style="margin:0;font-size:14px;color:#334155;">'
            '<strong>كلمة المرور المؤقتة:</strong></p>'
            '<div style="background:#1e293b;color:#e2e8f0;padding:12px 16px;border-radius:8px;'
            'font-family:monospace;font-size:14px;margin-top:8px;'
            'border:1px solid #334155;">{{ password }}</div>'
            '</div>'
            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ login_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">الدخول إلى لوحة التحكم &larr;</a>'
            '</div>'
            '<p style="font-size:13px;color:#94a3b8;">'
            'يرجى تغيير كلمة المرور الخاصة بك فور تسجيل الدخول لأول مرة لدواعٍ أمنية.</p>'
            '</div>',
            use_rtl=True
        ),
    },
    {
        'template_name': 'TENANT_BRIDGE_ROTATED',
        'category': 'Transactional',
        'subject_en': 'iRoad — API bridge key rotated — {{ company_name }}',
        'subject_ar': 'iRoad — تم تغيير مفتاح الربط — {{ company_name }}',
        'body_en': _wrap_email_body(
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'API Bridge Key Rotated 🔑</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 20px;">'
            'Hello {{ company_name }}, your API bridge key was rotated successfully. '
            'The previous key is now invalid. For security reasons, the new key is not shown here.</p>'
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="font-size:14px;color:#334155;">'
            'Please log in to your workspace portal to retrieve the new API bridge key.</p>'
            '</div>'
            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ portal_login_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">Login to Portal &rarr;</a>'
            '</div>'
        ),
        'body_ar': _wrap_email_body(
            '<div dir="rtl" style="text-align:right;">'
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'تم تغيير مفتاح الربط البرمجي 🔑</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 20px;">'
            'مرحباً {{ company_name }}، تم تغيير مفتاح الربط البرمجي بنجاح. '
            'تم إلغاء المفتاح السابق. لدواعٍ أمنية، لا يتم عرض المفتاح الجديد هنا.</p>'
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="font-size:14px;color:#334155;">'
            'يرجى تسجيل الدخول إلى بوابة العمل الخاصة بك للحصول على مفتاح الربط الجديد.</p>'
            '</div>'
            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ portal_login_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">تسجيل الدخول إلى البوابة &larr;</a>'
            '</div>'
            '</div>',
            use_rtl=True
        ),
    },
    {
        'template_name': 'INVOICE_PAID',
        'category': 'Transactional',
        'subject_en': 'Invoice {{ invoice_number }} issued',
        'subject_ar': 'تم إصدار الفاتورة {{ invoice_number }}',
        'body_en': _wrap_email_body(
            '<h2>Invoice Issued Successfully 🧾</h2>'
            '<p>Hello {{ tenant_name|default:company_name|default:"Customer" }},</p>'
            '<p>Your invoice has been generated and is now available in your account.</p>'
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin:20px 0;">'
            '<table style="width:100%;border-collapse:collapse;font-size:14px;color:#334155;">'
            '<tr><td style="padding:8px 0;font-weight:700;color:#6366f1;width:160px;">Invoice No:</td>'
            '<td style="padding:8px 0;">{{ invoice_number }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;color:#6366f1;">'
            'Issue Date:</td><td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ issue_date }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;color:#6366f1;">'
            'Due Date:</td><td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ due_date }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;color:#6366f1;">'
            'Currency:</td><td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ currency_code }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;color:#6366f1;">'
            'Status:</td><td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ invoice_status|default:"Issued" }}</td></tr>'
            '</table>'
            '</div>'
            '<div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:12px;padding:16px 18px;margin:0 0 20px;">'
            '<p style="margin:0;font-size:14px;color:#4338ca;"><strong>Total Amount:</strong> '
            '{{ invoice_amount_display|default:invoice_amount }}'
            '</p>'
            '</div>'
            '<p style="font-size:13px;color:#64748b;">'
            'For detailed line items, open the invoice in your iRoad portal.'
            '</p>'
        ),
        'body_ar': _wrap_email_body(
            '<div dir="rtl" style="text-align:right;">'
            '<h2>تم إصدار الفاتورة بنجاح 🧾</h2>'
            '<p>مرحباً {{ tenant_name|default:company_name|default:"العميل" }}،</p>'
            '<p>تم إنشاء فاتورتك وهي الآن متاحة في حسابك.</p>'
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin:20px 0;">'
            '<table style="width:100%;border-collapse:collapse;font-size:14px;color:#334155;">'
            '<tr><td style="padding:8px 0;font-weight:700;color:#6366f1;width:160px;">رقم الفاتورة:</td>'
            '<td style="padding:8px 0;">{{ invoice_number }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;color:#6366f1;">'
            'تاريخ الإصدار:</td><td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ issue_date }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;color:#6366f1;">'
            'تاريخ الاستحقاق:</td><td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ due_date }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;color:#6366f1;">'
            'العملة:</td><td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ currency_code }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;color:#6366f1;">'
            'الحالة:</td><td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ invoice_status|default:"Issued" }}</td></tr>'
            '</table>'
            '</div>'
            '<div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:12px;padding:16px 18px;margin:0 0 20px;">'
            '<p style="margin:0;font-size:14px;color:#4338ca;"><strong>إجمالي المبلغ:</strong> '
            '{{ invoice_amount_display|default:invoice_amount }}'
            '</p>'
            '</div>'
            '<p style="font-size:13px;color:#64748b;">'
            'للاطلاع على تفاصيل البنود، افتح الفاتورة من بوابة iRoad.'
            '</p>'
            '</div>',
            use_rtl=True
        ),
    },
    {
        'template_name': 'TESTING_EMAIL',
        'category': 'Transactional',
        'subject_en': 'iRoad — Test Email Notification',
        'subject_ar': 'iRoad — بريد إلكتروني تجريبي',
        'body_en': _wrap_email_body(
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'Test Email Successful ✅</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 20px;">'
            'This is a <strong>test email</strong> sent from the iRoad Communication module '
            'to verify that the email delivery pipeline is working correctly.</p>'
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<table style="width:100%;border-collapse:collapse;font-size:14px;color:#334155;">'
            '<tr><td style="padding:8px 0;font-weight:700;color:#6366f1;width:140px;">'
            'Sent To:</td><td style="padding:8px 0;">{{ recipient_email }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;'
            'color:#6366f1;">Sent At:</td>'
            '<td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ sent_at }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;'
            'color:#6366f1;">Gateway:</td>'
            '<td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ gateway_name|default:"Django SMTP" }}</td></tr>'
            '</table>'
            '</div>'
            '<div style="text-align:center;margin:24px 0 8px;">'
            '<span style="display:inline-block;background:linear-gradient(135deg,#10b981,#34d399);'
            'color:#fff;font-size:13px;font-weight:700;padding:10px 24px;border-radius:10px;'
            'letter-spacing:0.01em;">✓ Email Delivery Pipeline Operational</span>'
            '</div>'
            '<div style="height:1px;background:#e2e8f0;margin:28px 0;"></div>'
            '<p style="font-size:13px;color:#94a3b8;line-height:1.6;">'
            'If you received this email, the SMTP configuration and notification template system '
            'are fully operational. No action is required.</p>'
        ),
        'body_ar': _wrap_email_body(
            '<div dir="rtl" style="text-align:right;">'
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'البريد التجريبي ناجح ✅</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 20px;">'
            'هذا <strong>بريد إلكتروني تجريبي</strong> تم إرساله من وحدة الاتصالات في iRoad '
            'للتحقق من أن خط أنابيب تسليم البريد يعمل بشكل صحيح.</p>'
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<table style="width:100%;border-collapse:collapse;font-size:14px;color:#334155;">'
            '<tr><td style="padding:8px 0;font-weight:700;color:#6366f1;width:140px;">'
            'أُرسل إلى:</td><td style="padding:8px 0;">{{ recipient_email }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;'
            'color:#6366f1;">وقت الإرسال:</td>'
            '<td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ sent_at }}</td></tr>'
            '<tr><td style="padding:8px 0;border-top:1px solid #e2e8f0;font-weight:700;'
            'color:#6366f1;">البوابة:</td>'
            '<td style="padding:8px 0;border-top:1px solid #e2e8f0;">{{ gateway_name|default:"Django SMTP" }}</td></tr>'
            '</table>'
            '</div>'
            '<div style="text-align:center;margin:24px 0 8px;">'
            '<span style="display:inline-block;background:linear-gradient(135deg,#10b981,#34d399);'
            'color:#fff;font-size:13px;font-weight:700;padding:10px 24px;border-radius:10px;'
            'letter-spacing:0.01em;">✓ خط أنابيب تسليم البريد يعمل</span>'
            '</div>'
            '<div style="height:1px;background:#e2e8f0;margin:28px 0;"></div>'
            '<p style="font-size:13px;color:#94a3b8;line-height:1.6;">'
            'إذا تلقيت هذا البريد، فإن إعدادات SMTP ونظام قوالب الإشعارات '
            'يعملان بشكل كامل. لا يلزم اتخاذ أي إجراء.</p>'
            '</div>'
        ),
    },
]


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
    attachments=None,
):
    header_from = _normalize_from_email_header(gateway.sender_id, gateway.username_key)
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = header_from
    msg['To'] = to_email
    msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
    if html_body:
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    if attachments:
        from email.mime.application import MIMEApplication
        for filename, content, mimetype in attachments:
            part = MIMEApplication(content)
            part.add_header('Content-Disposition', 'attachment', filename=filename)
            msg.attach(part)

    port = gateway.port
    enc = gateway.encryption_type or 'TLS'
    host = gateway.host_url.strip()
    if port is None:
        port = 465 if enc == 'SSL' else 587

    def _send_once(*, send_from, smtp_host, smtp_port, smtp_enc, smtp_user, smtp_pass):
        envelope_from = _extract_sender_address(send_from, smtp_user)
        if smtp_enc == 'SSL':
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=60)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=60)
            if smtp_enc == 'TLS':
                server.starttls()
        try:
            server.login(smtp_user, smtp_pass)
            server.sendmail(envelope_from, [to_email], msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass

    try:
        try:
            _send_once(
                send_from=header_from,
                smtp_host=host,
                smtp_port=port,
                smtp_enc=enc,
                smtp_user=gateway.username_key,
                smtp_pass=gateway.password_secret,
            )
        except smtplib.SMTPAuthenticationError:
            fallback_user = getattr(settings, 'FALLBACK_EMAIL_HOST_USER', '')
            fallback_pass = getattr(settings, 'FALLBACK_EMAIL_HOST_PASSWORD', '')
            if not fallback_user or not fallback_pass:
                raise

            logger.warning(
                'Primary CommGateway SMTP auth failed; retrying with fallback SMTP account.',
            )
            fallback_host = getattr(settings, 'FALLBACK_EMAIL_HOST', 'smtp.gmail.com')
            fallback_port = getattr(settings, 'FALLBACK_EMAIL_PORT', 587)
            fallback_enc = (
                'SSL'
                if bool(getattr(settings, 'FALLBACK_EMAIL_USE_SSL', False))
                else ('TLS' if bool(getattr(settings, 'FALLBACK_EMAIL_USE_TLS', True)) else '')
            )
            fallback_from = _normalize_from_email_header(fallback_user, fallback_user)
            msg.replace_header('From', fallback_from)
            _send_once(
                send_from=fallback_from,
                smtp_host=fallback_host,
                smtp_port=fallback_port,
                smtp_enc=fallback_enc,
                smtp_user=fallback_user,
                smtp_pass=fallback_pass,
            )
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


def send_email_via_django_smtp(
    to_email,
    subject,
    text_body,
    html_body=None,
    *,
    trigger_source='Direct: Email',
    client_id=None,
    attachments=None,
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
    from_email = _resolve_safe_from_email(from_email)
    from_email = _normalize_from_email_header(
        from_email,
        getattr(settings, 'EMAIL_HOST_USER', ''),
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
    
    if attachments:
        for filename, content, mimetype in attachments:
            msg.attach(filename, content, mimetype)
    try:
        msg.send(fail_silently=False)
    except smtplib.SMTPException:
        logger.warning(
            'Django SMTP backend send failed; retrying via direct fallback SMTP.',
        )
        _send_via_fallback_smtp(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
    try:
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
    attachments=None,
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
            attachments=attachments,
        )
        return True
    return send_email_via_django_smtp(
        to_email,
        subject,
        text_body,
        html_body,
        trigger_source=trigger_source,
        client_id=client_id,
        attachments=attachments,
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
    Send SMS through the configured active gateway.

    Supported payload styles:
    - Twilio API endpoints (form-encoded with account SID + auth token)
    - Generic providers (JSON POST: {"to": "...", "message": "...", "from": "..."})
    """
    url = (gateway.host_url or '').strip()
    provider = (gateway.provider_name or '').strip().lower()
    headers = {}
    payload = None

    # Twilio-style endpoints: /2010-04-01/Accounts/{SID}/Messages.json
    # We also treat providers named "twilio" as Twilio payload mode.
    if 'twilio' in provider or 'api.twilio.com' in url:
        twilio_sender = (gateway.sender_id or '').strip()
        form_data = {
            'To': recipient_phone,
            'Body': message,
        }
        if twilio_sender:
            form_data['From'] = twilio_sender
        payload = urllib.parse.urlencode(form_data).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    else:
        payload = json.dumps({
            'to': recipient_phone,
            'message': message,
            'from': (gateway.sender_id or '').strip(),
        }).encode('utf-8')
        headers['Content-Type'] = 'application/json'

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
    return Template(raw_text or '').render(
        Context(_merge_template_context(context_dict)),
    )


def ensure_default_notification_templates(created_by=None):
    """
    Ensure required email templates exist for auth + tenant notifications.
    Returns number of newly created templates.
    """
    from superadmin.models import EventMapping, NotificationTemplate

    created = 0
    for item in DEFAULT_NOTIFICATION_EMAIL_TEMPLATES:
        _obj, was_created = NotificationTemplate.objects.get_or_create(
            template_name=item['template_name'],
            defaults={
                'channel_type': 'Email',
                'category': item['category'],
                'subject_en': item['subject_en'],
                'subject_ar': item['subject_ar'],
                'body_en': item['body_en'],
                'body_ar': item['body_ar'],
                'is_active': True,
                'created_by': created_by,
            },
        )
        if was_created:
            created += 1

    # Ensure OTP_Requested event is mapped to the default OTP template.
    otp_template = NotificationTemplate.objects.filter(
        template_name='AUTH_LOGIN_OTP',
        channel_type='Email',
    ).first()
    if otp_template:
        EventMapping.objects.update_or_create(
            system_event='OTP_Requested',
            defaults={
                'primary_channel': 'Email',
                'primary_template': otp_template,
                'is_active': True,
                'updated_by': created_by,
            },
        )

    # Ensure New_Tenant_Registered event is mapped to the default Welcome template.
    welcome_template = NotificationTemplate.objects.filter(
        template_name='TENANT_WELCOME_EMAIL',
        channel_type='Email',
    ).first()
    if welcome_template:
        EventMapping.objects.update_or_create(
            system_event='New_Tenant_Registered',
            defaults={
                'primary_channel': 'Email',
                'primary_template': welcome_template,
                'is_active': True,
                'updated_by': created_by,
            },
        )
    return created


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


def send_named_notification_email(
    template_name,
    *,
    recipient_email,
    context_dict=None,
    language='en',
    default_subject='Notification',
    trigger_source=None,
    force_django_smtp=False,
    attachments=None,
):
    """
    Send an Email NotificationTemplate selected by ``template_name``.
    Returns True when sent, False when no active template is found.
    """
    from superadmin.models import NotificationTemplate

    template_obj = (
        NotificationTemplate.objects.filter(
            template_name=template_name,
            channel_type='Email',
            is_active=True,
        )
        .order_by('-created_at')
        .first()
    )
    if not template_obj:
        return False

    subject, body = render_notification_template(
        template_obj,
        context_dict=context_dict,
        language=language,
    )
    subject = (subject or default_subject).strip() or default_subject
    text_body = strip_tags(body).strip() or body
    source = trigger_source or f'TemplateName: {template_name}'

    if force_django_smtp:
        return send_email_via_django_smtp(
            recipient_email,
            subject,
            text_body,
            body,
            trigger_source=source,
            attachments=attachments,
        )
    return send_transactional_email(
        recipient_email,
        subject,
        text_body,
        body,
        trigger_source=source,
        attachments=attachments,
    )


def dispatch_event_notification(
    event_code,
    *,
    recipient_email=None,
    recipient_phone=None,
    context_dict=None,
    language='en',
    force_django_smtp=False,
    use_async_tasks=True,
    attachments=None,
):
    """
    Generic dispatcher:
    1) resolve active EventMapping by event_code
    2) render mapped template using {{variables}}
    3) send via primary channel, fallback channel on failure
    """
    from superadmin.models import EventMapping

    # Queue the entire event dispatch as one background job so
    # fallback logic runs in the same execution context.
    if use_async_tasks:
        from superadmin.tasks import dispatch_event_notification_task

        dispatch_event_notification_task.delay(
            event_code,
            recipient_email=recipient_email,
            recipient_phone=recipient_phone,
            context_dict=context_dict or {},
            language=language,
            force_django_smtp=force_django_smtp,
        )
        return True

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
            if force_django_smtp:
                return send_email_via_django_smtp(
                    recipient_email,
                    subject or 'Notification',
                    strip_tags(body),
                    body,
                    attachments=attachments,
                )
            return send_transactional_email(
                recipient_email,
                subject or 'Notification',
                strip_tags(body),
                body,
                attachments=attachments,
                trigger_source=f'Event: {event_code}',
            )
        if channel == 'SMS':
            if not recipient_phone:
                raise ValueError('recipient_phone is required for SMS channel')
            sms_text = strip_tags(body).strip() or body.strip()
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
    from superadmin.models import (
        AdminUser,
        InternalAlertNotification,
        InternalAlertRoute,
    )
    from superadmin.tasks import send_email_task
    def _send_internal_alert_email(recipient_email):
        """Prefer async queue; fallback to direct SMTP if queue is unavailable."""
        try:
            send_email_task.delay(recipient_email, subject, body, None)
            return True
        except Exception:
            logger.exception(
                'Internal alert queue dispatch failed for %s; falling back to direct SMTP.',
                recipient_email,
            )
            try:
                send_email_via_django_smtp(
                    recipient_email,
                    subject,
                    body,
                    None,
                    trigger_source=f'InternalAlert: {event_code}',
                )
                return True
            except Exception:
                logger.exception(
                    'Internal alert direct SMTP failed for %s',
                    recipient_email,
                )
                return False


    routes = InternalAlertRoute.objects.filter(trigger_event=event_code, is_active=True)
    if not routes.exists():
        return 0

    ctx = context_dict or {}
    # InternalAlertNotification.context_payload is JSONField, so sanitize any
    # non-JSON values (e.g., model instances) before persisting notifications.
    safe_ctx = json.loads(json.dumps(ctx, default=str, ensure_ascii=True))
    subject = f'Internal Alert: {event_code}'
    body = (
        f'Event "{event_code}" triggered.\n\n'
        f'Context:\n{json.dumps(safe_ctx, default=str, ensure_ascii=True)}'
    )
    sent_to = set()
    notified_admin_ids = set()
    title = f'Internal Alert - {event_code.replace("_", " ")}'
    message = safe_ctx.get('message') or body[:1000]
    for route in routes.iterator():
        email = ''
        if route.notify_custom_email:
            email = route.notify_custom_email.strip().lower()
            if email and email not in sent_to:
                if _send_internal_alert_email(email):
                    sent_to.add(email)

        if email:
            admin = AdminUser.objects.filter(
                email__iexact=email,
                status='Active',
                is_deleted=False,
            ).first()
            if admin and admin.pk not in notified_admin_ids:
                InternalAlertNotification.objects.create(
                    admin_user=admin,
                    route=route,
                    trigger_event=event_code,
                    title=title,
                    message=message,
                    context_payload=safe_ctx,
                )
                notified_admin_ids.add(admin.pk)
        if route.notify_role_id:
            admins = AdminUser.objects.filter(
                role_id=route.notify_role_id,
                status='Active',
                is_deleted=False,
            ).values_list('email', flat=True)
            for email in admins:
                norm = (email or '').strip().lower()
                if norm and norm not in sent_to:
                    if _send_internal_alert_email(norm):
                        sent_to.add(norm)
            for admin in AdminUser.objects.filter(
                role_id=route.notify_role_id,
                status='Active',
                is_deleted=False,
            ).only('id'):
                if admin.pk in notified_admin_ids:
                    continue
                InternalAlertNotification.objects.create(
                    admin_user=admin,
                    route=route,
                    trigger_event=event_code,
                    title=title,
                    message=message,
                    context_payload=safe_ctx,
                )
                notified_admin_ids.add(admin.pk)
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
    invite_url='',
):
    """
    Welcome email after subscriber provisioning (CP-PCS-P1 §4 handover).
    Now uses the centralized dispatch_event_notification engine.
    """
    set_password_url = (invite_url or '').strip() or 'http://127.0.0.1:8000/set-password/'
    ctx = {
        'tenant': tenant,
        'tenant_id': str(tenant.tenant_id),
        'company_name': tenant.company_name,
        'primary_email': tenant.primary_email,
        'invite_url': set_password_url,
        'portal_login_url': set_password_url,
        'api_bridge_key': api_bridge_key_plain or '',
        'portal_bootstrap_password': portal_bootstrap_password_plain or '',
        'message': f'New tenant "{tenant.company_name}" registered ({tenant.primary_email}).',
    }
    
    # We use the dispatch_event_notification engine so that:
    # 1. The Welcome Email is sent to the tenant (primary_template).
    # 2. Internal alerts are routed to admins (dispatch_internal_alerts).
    # We force synchronous dispatch for registration so we can verify delivery immediately.
    return dispatch_event_notification(
        'New_Tenant_Registered',
        recipient_email=tenant.primary_email,
        context_dict=ctx,
        language='en',
        force_django_smtp=True,
        use_async_tasks=False,
    )


def send_tenant_bridge_rotated_email(tenant, api_bridge_key_plain):
    """Notify subscriber that the API bridge key was rotated; plaintext only in email."""
    ctx = {
        'tenant': tenant,
        'api_bridge_key': api_bridge_key_plain,
        'company_name': tenant.company_name,
    }
    ctx = _merge_template_context(ctx)
    if send_named_notification_email(
        'TENANT_BRIDGE_ROTATED',
        recipient_email=tenant.primary_email,
        context_dict=ctx,
        language='en',
        default_subject=f'iRoad — API bridge key rotated — {tenant.company_name}',
        trigger_source='TemplateName: TENANT_BRIDGE_ROTATED',
        force_django_smtp=True,
    ):
        return True

    html = render_to_string('tenant/emails/api_bridge_rotated.html', ctx)
    text = strip_tags(html)
    subject = f'iRoad — API bridge key rotated — {tenant.company_name}'
    return send_email_via_django_smtp(tenant.primary_email, subject, text, html)
