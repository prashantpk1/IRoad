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
import urllib.parse
from base64 import b64encode
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

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


def _wrap_email_body(inner_html, email_title="iRoad Logistics", preheader="iRoad Logistics — Secure notification", use_rtl=False):
    base_html = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>{% block email_title %}iRoad Logistics{% endblock %}</title>
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
        body { margin: 0 !important; padding: 0 !important; width: 100% !important; }

        /* Typography */
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #334155;
            background-color: #f1f5f9;
        }

        /* Wrapper */
        .email-wrapper {
            width: 100%;
            max-width: 640px;
            margin: 0 auto;
            background: #ffffff;
        }

        /* Header */
        .email-header {
            background: linear-gradient(135deg, #4f46e5 0%, #6366f1 50%, #818cf8 100%);
            padding: 0;
            text-align: center;
        }
        .email-header-inner {
            padding: 36px 40px 32px;
        }
        .email-logo {
            width: 52px;
            height: 52px;
            border-radius: 14px;
            margin-bottom: 14px;
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

        /* Button */
        .button-wrapper { text-align: center; margin: 28px 0; }
        .button {
            background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
            color: #ffffff !important;
            padding: 14px 32px;
            text-decoration: none;
            border-radius: 10px;
            font-weight: 700;
            font-size: 15px;
            display: inline-block;
            letter-spacing: 0.01em;
            box-shadow: 0 4px 14px rgba(79, 70, 229, 0.3);
        }

        /* Info box */
        .invite-info {
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            padding: 20px 22px;
            border-radius: 12px;
            border: 1px solid #e2e8f0;
            margin-bottom: 20px;
        }

        /* Secret / code box */
        .secret-box {
            background-color: #1e293b;
            color: #e2e8f0;
            padding: 14px 18px;
            border-radius: 10px;
            font-family: 'SF Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 13px;
            word-break: break-all;
            margin: 12px 0;
            letter-spacing: 0.02em;
            border: 1px solid #334155;
        }

        /* Labels */
        .label {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #6366f1;
            margin-bottom: 6px;
        }

        /* Warning / expiry */
        .expiry {
            font-size: 13px;
            color: #ef4444;
            margin-top: 20px;
            font-weight: 600;
        }

        /* Muted text */
        .muted {
            font-size: 13px;
            color: #94a3b8;
            margin-top: 12px;
            line-height: 1.6;
        }

        /* Divider */
        .email-divider {
            height: 1px;
            background: #e2e8f0;
            margin: 28px 0;
            border: none;
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
        .footer-links {
            margin: 12px 0 0;
        }
        .footer-links a {
            color: #6366f1;
            text-decoration: none;
            font-size: 12px;
            font-weight: 600;
            margin: 0 8px;
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

        /* Responsive */
        @media only screen and (max-width: 600px) {
            .email-wrapper { width: 100% !important; }
            .email-body { padding: 28px 24px !important; }
            .email-header-inner { padding: 28px 24px 24px !important; }
            .email-footer { padding: 24px 24px 28px !important; }
            .email-brand { font-size: 22px !important; }
        }
    </style>
    {% block extra_head %}{% endblock %}
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9;">

    <!-- Preheader (hidden preview text for email clients) -->
    <div style="display: none; font-size: 1px; color: #f1f5f9; line-height: 1px; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden;">
        {% block preheader %}iRoad Logistics — Secure notification{% endblock %}
    </div>

    <!-- Outer container -->
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f1f5f9;">
        <tr>
            <td align="center" style="padding: 40px 16px;">

                <!-- Email card -->
                <table role="presentation" border="0" cellpadding="0" cellspacing="0" class="email-wrapper" style="max-width: 640px; width: 100%; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 24px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04);">

                    <!-- HEADER -->
                    <tr>
                        <td class="email-header">
                            <div class="email-header-inner">
                                {% load static %}
                                <img src="https://iroad-assets.s3.amazonaws.com/logo.png" alt="iRoad" class="email-logo" style="width: 52px; height: 52px; border-radius: 14px;">
                                <h1 class="email-brand">iRoad</h1>
                                <p class="email-brand-sub">Logistics Management Platform</p>
                            </div>
                            <div class="header-divider"></div>
                        </td>
                    </tr>

                    <!-- BODY -->
                    <tr>
                        <td class="email-body">
                            {% block content %}{% endblock %}
                        </td>
                    </tr>

                    <!-- FOOTER -->
                    <tr>
                        <td class="email-footer">
                            <div class="footer-logo-text">iRoad</div>
                            <p class="footer-text">
                                &copy; 2026 iRoad Logistics. All rights reserved.<br>
                                This is an automated system notification. Please do not reply to this email.
                            </p>
                            <div class="footer-links">
                                <a href="#">Privacy Policy</a>
                                <span style="color: #cbd5e1;">&middot;</span>
                                <a href="#">Terms of Service</a>
                                <span style="color: #cbd5e1;">&middot;</span>
                                <a href="#">Support</a>
                            </div>
                            <div class="footer-badge">Secured &amp; Encrypted</div>
                        </td>
                    </tr>

                </table>
                <!-- /Email card -->

            </td>
        </tr>
    </table>

</body>
</html>

"""
    import re
    if use_rtl:
        inner_html = '<div dir="rtl" style="text-align:right;">' + inner_html + '</div>'
    
    html = base_html
    html = re.sub(r'{%\s*block\s+email_title\s*%}.*?{%\s*endblock\s*%}', email_title, html, flags=re.DOTALL)
    html = re.sub(r'{%\s*block\s+preheader\s*%}.*?{%\s*endblock\s*%}', preheader, html, flags=re.DOTALL)
    html = re.sub(r'{%\s*block\s+content\s*%}.*?{%\s*endblock\s*%}', inner_html, html, flags=re.DOTALL)
    html = re.sub(r'{%\s*block\s+extra_head\s*%}{%\s*endblock\s*%}', '', html)
    
    return html

DEFAULT_NOTIFICATION_EMAIL_TEMPLATES = [
    {
        'template_name': 'AUTH_PASSWORD_RESET',
        'category': 'Transactional',
        'subject_en': 'Reset Your iRoad Password',
        'subject_ar': 'إعادة تعيين كلمة مرور iRoad',
        'body_en': _wrap_email_body(
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'Reset Your Password 🔐</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 16px;">'
            'Hello {{ admin_user.first_name|default:"Admin" }},</p>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 24px;">'
            'We received a request to reset the password for your iRoad admin account. '
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
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'إعادة تعيين كلمة المرور 🔐</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 16px;">'
            'مرحباً {{ admin_user.first_name|default:"Admin" }}،</p>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 24px;">'
            'تلقينا طلباً لإعادة تعيين كلمة المرور لحسابك في iRoad. '
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
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'You\'re Invited! 🎉</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 16px;">'
            'Hello {{ admin_user.first_name|default:"Admin" }},</p>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 24px;">'
            'You have been invited to join the <strong>iRoad</strong> admin panel. '
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
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'لقد تمت دعوتك! 🎉</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 16px;">'
            'مرحباً {{ admin_user.first_name|default:"Admin" }}،</p>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 24px;">'
            'تمت دعوتك للانضمام إلى لوحة تحكم <strong>iRoad</strong>. '
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
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'Welcome, {{ company_name }}! 🚀</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 20px;">'
            'Your subscriber workspace has been provisioned and is ready to use. '
            'Below are your sign-in credentials and integration keys.</p>'
            
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="font-size:11px;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.06em;color:#6366f1;margin:0 0 6px;">Portal Credentials</p>'
            '<p style="margin:8px 0 4px;font-size:14px;color:#334155;">'
            '<strong>Login email:</strong> {{ tenant.primary_email }}</p>'
            '<p style="margin:4px 0 0;font-size:14px;color:#334155;">'
            '<strong>Initial password:</strong> <span style="color:#ef4444;font-size:12px;">(change after sign-in)</span></p>'
            '<div style="background:#1e293b;color:#e2e8f0;padding:14px 18px;border-radius:10px;'
            'font-family:monospace;font-size:13px;word-break:break-all;margin:12px 0;'
            'border:1px solid #334155;">{{ portal_bootstrap_password }}</div>'
            '</div>'

            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ portal_login_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">Open Workspace Sign-in &rarr;</a>'
            '</div>'

            '<div style="height:1px;background:#e2e8f0;margin:28px 0;"></div>'

            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="font-size:11px;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.06em;color:#6366f1;margin:0 0 6px;">Tenant Identifier</p>'
            '<p style="margin:4px 0 8px;font-size:13px;color:#64748b;">'
            'Use with <code>X-Tenant-ID</code> header on API calls:</p>'
            '<div style="background:#1e293b;color:#e2e8f0;padding:14px 18px;border-radius:10px;'
            'font-family:monospace;font-size:13px;word-break:break-all;margin:0;'
            'border:1px solid #334155;">{{ tenant.tenant_id }}</div>'
            '</div>'

            '<p style="font-size:11px;font-weight:700;text-transform:uppercase;color:#6366f1;margin:0 0 6px;">API Bridge Key</p>'
            '<p style="font-size:13px;color:#64748b;margin-bottom:12px;">'
            'Authentication secret for the bridge endpoint. Store this securely — it is never shown again.</p>'
            '<div style="background:#1e293b;color:#e2e8f0;padding:14px 18px;border-radius:10px;'
            'font-family:monospace;font-size:13px;word-break:break-all;margin:0;'
            'border:1px solid #334155;">{{ api_bridge_key }}</div>'
        ),
        'body_ar': _wrap_email_body(
            '<div dir="rtl" style="text-align:right;">'
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'مرحباً بك في iRoad، {{ company_name }}! 🚀</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 20px;">'
            'تم تجهيز مساحة العمل الخاصة بك وهي جاهزة للاستخدام الآن. أدناه بيانات الدخول ومفاتيح التكامل.</p>'
            
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="font-size:11px;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.06em;color:#6366f1;margin:0 0 6px;">بيانات دخول البوابة</p>'
            '<p style="margin:8px 0 4px;font-size:14px;color:#334155;">'
            '<strong>البريد الإلكتروني:</strong> {{ tenant.primary_email }}</p>'
            '<p style="margin:4px 0 0;font-size:14px;color:#334155;">'
            '<strong>كلمة المرور الأولية:</strong> <span style="color:#ef4444;font-size:12px;">(يرجى تغييرها بعد الدخول)</span></p>'
            '<div style="background:#1e293b;color:#e2e8f0;padding:14px 18px;border-radius:10px;'
            'font-family:monospace;font-size:13px;word-break:break-all;margin:12px 0;'
            'border:1px solid #334155;">{{ portal_bootstrap_password }}</div>'
            '</div>'

            '<div style="text-align:center;margin:28px 0;">'
            '<a href="{{ portal_login_url }}" style="background:linear-gradient(135deg,#4f46e5,#6366f1);'
            'color:#fff!important;padding:14px 32px;text-decoration:none;border-radius:10px;'
            'font-weight:700;font-size:15px;display:inline-block;'
            'box-shadow:0 4px 14px rgba(79,70,229,.3);">فتح بوابة الدخول &larr;</a>'
            '</div>'

            '<div style="height:1px;background:#e2e8f0;margin:28px 0;"></div>'

            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="font-size:11px;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.06em;color:#6366f1;margin:0 0 6px;">معرف المستأجر (Tenant ID)</p>'
            '<p style="margin:4px 0 8px;font-size:13px;color:#64748b;">'
            'استخدمه مع خاصية <code>X-Tenant-ID</code> في ترويسة طلبات API:</p>'
            '<div style="background:#1e293b;color:#e2e8f0;padding:14px 18px;border-radius:10px;'
            'font-family:monospace;font-size:13px;word-break:break-all;margin:0;'
            'border:1px solid #334155;">{{ tenant.tenant_id }}</div>'
            '</div>'

            '<p style="font-size:11px;font-weight:700;text-transform:uppercase;color:#6366f1;margin:0 0 6px;">مفتاح الربط البرمجي (API)</p>'
            '<p style="font-size:13px;color:#64748b;margin-bottom:12px;">'
            'سر المصادقة لنقطة نهاية الجسر. يرجى الاحتفاظ به بشكل آمن - لن يتم عرضه مرة أخرى.</p>'
            '<div style="background:#1e293b;color:#e2e8f0;padding:14px 18px;border-radius:10px;'
            'font-family:monospace;font-size:13px;word-break:break-all;margin:0;'
            'border:1px solid #334155;">{{ api_bridge_key }}</div>'
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
            'Your previous key has been revoked.</p>'
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="font-size:11px;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.06em;color:#6366f1;margin:0 0 6px;">New API Bridge Key</p>'
            '<div style="background:#1e293b;color:#e2e8f0;padding:14px 18px;border-radius:10px;'
            'font-family:monospace;font-size:13px;word-break:break-all;margin:0;'
            'border:1px solid #334155;">{{ api_bridge_key }}</div>'
            '</div>'
            '<p style="font-size:13px;color:#ef4444;font-weight:600;margin-top:20px;">'
            '⚠️ Older keys no longer work. Update all integrations immediately.</p>'
        ),
        'body_ar': _wrap_email_body(
            '<div dir="rtl" style="text-align:right;">'
            '<h2 style="color:#1e293b;margin:0 0 16px;font-size:22px;font-weight:700;">'
            'تم تغيير مفتاح الربط البرمجي 🔑</h2>'
            '<p style="font-size:15px;color:#475569;line-height:1.7;margin:0 0 20px;">'
            'مرحباً {{ company_name }}، تم تغيير مفتاح الربط البرمجي بنجاح. '
            'تم إلغاء المفتاح السابق.</p>'
            '<div style="background:linear-gradient(135deg,#f8fafc,#f1f5f9);'
            'padding:20px 22px;border-radius:12px;border:1px solid #e2e8f0;margin-bottom:20px;">'
            '<p style="font-size:11px;font-weight:700;text-transform:uppercase;'
            'letter-spacing:0.06em;color:#6366f1;margin:0 0 6px;">المفتاح الجديد</p>'
            '<div style="background:#1e293b;color:#e2e8f0;padding:14px 18px;border-radius:10px;'
            'font-family:monospace;font-size:13px;word-break:break-all;margin:0;'
            'border:1px solid #334155;">{{ api_bridge_key }}</div>'
            '</div>'
            '<p style="font-size:13px;color:#ef4444;font-weight:600;margin-top:20px;">'
            '⚠️ المفاتيح القديمة لم تعد تعمل. قم بتحديث جميع التكاملات فوراً.</p>'
            '</div>'
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
    return Template(raw_text or '').render(Context(context_dict or {}))


def ensure_default_notification_templates(created_by=None):
    """
    Ensure required email templates exist for auth + tenant notifications.
    Returns number of newly created templates.
    """
    from superadmin.models import NotificationTemplate

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
        )
    return send_transactional_email(
        recipient_email,
        subject,
        text_body,
        body,
        trigger_source=source,
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
    # Preferred path: explicit named template from Notification Templates screen.
    # This lets ops edit content without code changes.
    if send_named_notification_email(
        'TENANT_WELCOME_EMAIL',
        recipient_email=tenant.primary_email,
        context_dict=ctx,
        language='en',
        default_subject=f'Welcome to iRoad — {tenant.company_name}',
        trigger_source='TemplateName: TENANT_WELCOME_EMAIL',
        force_django_smtp=True,
    ):
        return True

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
