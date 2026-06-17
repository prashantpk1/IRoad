"""Tenant organization system configuration (currency, locale, formats)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone as django_timezone
from django.utils import translation

DEFAULT_TENANT_SYSTEM_CONFIG = {
    'base_currency_code': 'SAR',
    'system_language': 'en',
    'timezone': 'Asia/Riyadh',
    'date_format': 'DD/MM/YYYY',
    'number_format': '1,234.56',
    'negative_format': '-100',
}

DATE_FORMAT_STRFTIME = {
    'DD/MM/YYYY': '%d/%m/%Y',
    'MM/DD/YYYY': '%m/%d/%Y',
    'YYYY-MM-DD': '%Y-%m-%d',
}

DATE_FORMAT_DATETIME_STRFTIME = {
    'DD/MM/YYYY': '%d/%m/%Y %H:%M',
    'MM/DD/YYYY': '%m/%d/%Y %H:%M',
    'YYYY-MM-DD': '%Y-%m-%d %H:%M',
}

JS_LOCALE_BY_LANGUAGE = {
    'ar': 'ar-SA',
    'en': 'en-US',
}


def config_dict_from_organization_profile(org) -> dict:
    """Build a normalized config dict from OrganizationProfile (or defaults)."""
    if org is None:
        return dict(DEFAULT_TENANT_SYSTEM_CONFIG)

    base_currency = (getattr(org, 'base_currency_code', '') or '').strip().upper()
    return {
        'base_currency_code': base_currency or DEFAULT_TENANT_SYSTEM_CONFIG['base_currency_code'],
        'system_language': (getattr(org, 'system_language', '') or 'en').strip() or 'en',
        'timezone': (getattr(org, 'timezone', '') or 'Asia/Riyadh').strip() or 'Asia/Riyadh',
        'date_format': (getattr(org, 'date_format', '') or 'DD/MM/YYYY').strip() or 'DD/MM/YYYY',
        'number_format': (getattr(org, 'number_format', '') or '1,234.56').strip() or '1,234.56',
        'negative_format': (getattr(org, 'negative_format', '') or '-100').strip() or '-100',
    }


def resolve_tenant_system_config(request) -> dict:
    """Load tenant system configuration for the current portal request."""
    cached = getattr(request, 'tenant_system_config', None)
    if cached:
        return cached

    registry = getattr(request, 'tenant_workspace_registry', None)
    if registry is None:
        return dict(DEFAULT_TENANT_SYSTEM_CONFIG)

    from tenant_workspace.models import OrganizationProfile

    org = OrganizationProfile.objects.order_by('-updated_at', '-created_at').first()
    return config_dict_from_organization_profile(org)


def activate_tenant_system_config(config: dict) -> None:
    """Apply language and timezone for the current request thread."""
    language = (config.get('system_language') or 'en').strip() or 'en'
    translation.activate(language)

    tz_name = (config.get('timezone') or 'Asia/Riyadh').strip() or 'Asia/Riyadh'
    try:
        django_timezone.activate(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        django_timezone.activate(ZoneInfo('Asia/Riyadh'))


def js_locale_for_config(config: dict) -> str:
    language = (config.get('system_language') or 'en').strip() or 'en'
    return JS_LOCALE_BY_LANGUAGE.get(language, 'en-US')


def _quantize_decimal(value, decimal_places: int) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal('0')
    quant = Decimal('1').scaleb(-decimal_places)
    return amount.quantize(quant, rounding=ROUND_HALF_UP)


def _number_separators(number_format: str) -> tuple[str, str]:
    if number_format == '1.234,56':
        return '.', ','
    return ',', '.'


def format_tenant_number(value, config: dict | None = None, *, decimal_places: int = 2) -> str:
    """Format a numeric value using tenant number/negative format settings."""
    config = config or DEFAULT_TENANT_SYSTEM_CONFIG
    amount = _quantize_decimal(value, decimal_places)
    is_negative = amount < 0
    amount = abs(amount)

    thousands_sep, decimal_sep = _number_separators(config.get('number_format', '1,234.56'))
    formatted = f'{amount:,.{decimal_places}f}'
    if thousands_sep != ',' or decimal_sep != '.':
        formatted = (
            formatted.replace(',', '\x00')
            .replace('.', '\x01')
            .replace('\x00', thousands_sep)
            .replace('\x01', decimal_sep)
        )

    if is_negative:
        if config.get('negative_format') == '(100)':
            return f'({formatted})'
        return f'-{formatted}'
    return formatted


def format_tenant_currency(
    value,
    currency_code: str,
    config: dict | None = None,
    *,
    decimal_places: int = 2,
) -> str:
    """Format amount with currency code prefix."""
    config = config or DEFAULT_TENANT_SYSTEM_CONFIG
    code = (currency_code or config.get('base_currency_code') or 'SAR').strip().upper()
    return f'{code} {format_tenant_number(value, config, decimal_places=decimal_places)}'


def _to_aware_datetime(value):
    if value is None:
        return None
    if hasattr(value, 'hour'):
        if django_timezone.is_naive(value):
            return django_timezone.make_aware(value, django_timezone.get_current_timezone())
        return django_timezone.localtime(value)
    return value


def format_tenant_date(value, config: dict | None = None, *, include_time: bool = False) -> str:
    """Format a date/datetime using tenant date format and active timezone."""
    config = config or DEFAULT_TENANT_SYSTEM_CONFIG
    dt = _to_aware_datetime(value)
    if dt is None:
        return ''

    date_format = config.get('date_format', 'DD/MM/YYYY')
    if include_time:
        pattern = DATE_FORMAT_DATETIME_STRFTIME.get(date_format, '%d/%m/%Y %H:%M')
    else:
        if hasattr(dt, 'hour') and not include_time:
            dt = dt.date()
        pattern = DATE_FORMAT_STRFTIME.get(date_format, '%d/%m/%Y')
    return dt.strftime(pattern)


def tenant_system_config_for_js(config: dict | None = None) -> dict:
    """Serializable config for client-side formatting (navbar clock, etc.)."""
    config = config or DEFAULT_TENANT_SYSTEM_CONFIG
    return {
        'base_currency_code': config.get('base_currency_code') or 'SAR',
        'system_language': config.get('system_language') or 'en',
        'timezone': config.get('timezone') or 'Asia/Riyadh',
        'date_format': config.get('date_format') or 'DD/MM/YYYY',
        'number_format': config.get('number_format') or '1,234.56',
        'negative_format': config.get('negative_format') or '-100',
        'js_locale': js_locale_for_config(config),
        'is_rtl': (config.get('system_language') or 'en') == 'ar',
    }
