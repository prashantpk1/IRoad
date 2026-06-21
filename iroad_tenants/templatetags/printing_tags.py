from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def print_date(value):
    if not value:
        return '—'
    if hasattr(value, 'date') and callable(value.date):
        value = timezone.localtime(value).date() if hasattr(value, 'hour') else value
    return value.strftime('%d / %m / %Y')


@register.filter
def print_datetime(value):
    if not value:
        return '—'
    local = timezone.localtime(value)
    return local.strftime('%d / %m / %Y — %I:%M %p')


@register.filter
def print_decimal(value, places=2):
    if value in (None, ''):
        return '—'
    try:
        return f'{float(value):,.{int(places)}f}'
    except (TypeError, ValueError):
        return str(value)


@register.filter
def print_money(value, currency='SAR'):
    if value in (None, ''):
        return '—'
    code = (currency or 'SAR').strip() or 'SAR'
    try:
        return f'{float(value):,.2f} {code}'
    except (TypeError, ValueError):
        return f'{value} {code}'


@register.filter
def print_status_pill(value):
    text = str(value or '').strip().lower()
    if text in {'active', 'confirmed', 'completed', 'verified', 'converted', 'valid', 'closed', 'executed'}:
        return 'confirmed'
    if text in {'draft', 'pending', 'not completed', 'not_completed', 'in progress', 'in_progress'}:
        return 'pending'
    if text in {'cancelled', 'canceled', 'inactive', 'expired', 'suspended'}:
        return 'cancelled'
    if text in {'cod', 'debit', 'credit'}:
        return text
    return 'pending'


@register.filter
def print_doc_status_label(value):
    text = str(value or '').strip()
    if not text or text.lower() in {'not provided', 'not_provided'}:
        return '—'
    if text.lower() == 'valid':
        return 'Valid'
    if text.lower() == 'expired':
        return 'Expired'
    return text


@register.filter
def print_phone(value):
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if not digits:
        return '—'
    if digits.startswith('966') and len(digits) >= 12:
        return f'+966 {digits[3:5]} {digits[5:8]} {digits[8:]}'
    return digits
