from django import template

from iroad_tenants.tenant_system_config import (
    DEFAULT_TENANT_SYSTEM_CONFIG,
    format_tenant_currency,
    format_tenant_date,
    format_tenant_number,
)

register = template.Library()


def _config_from_context(context):
    return context.get('tenant_system_config') or DEFAULT_TENANT_SYSTEM_CONFIG


@register.simple_tag(takes_context=True)
def tenant_date(context, value, include_time=False):
    return format_tenant_date(
        value,
        _config_from_context(context),
        include_time=str(include_time).lower() in {'1', 'true', 'time', 'datetime'},
    )


@register.simple_tag(takes_context=True)
def tenant_number(context, value, decimal_places=2):
    return format_tenant_number(
        value,
        _config_from_context(context),
        decimal_places=int(decimal_places),
    )


@register.simple_tag(takes_context=True)
def tenant_currency(context, value, currency_code=''):
    config = _config_from_context(context)
    code = currency_code or config.get('base_currency_code') or 'SAR'
    return format_tenant_currency(value, code, config)
