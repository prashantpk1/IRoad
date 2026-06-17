from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from iroad_tenants.middleware import TenantSystemConfigurationMiddleware
from iroad_tenants.tenant_system_config import (
    DEFAULT_TENANT_SYSTEM_CONFIG,
    activate_tenant_system_config,
    config_dict_from_organization_profile,
    format_tenant_currency,
    format_tenant_date,
    format_tenant_number,
    tenant_system_config_for_js,
)


class _OrgStub:
    base_currency_code = 'USD'
    system_language = 'ar'
    timezone = 'Asia/Dubai'
    date_format = 'YYYY-MM-DD'
    number_format = '1.234,56'
    negative_format = '(100)'


class TenantSystemConfigTests(SimpleTestCase):
    def test_config_dict_from_organization_profile(self):
        config = config_dict_from_organization_profile(_OrgStub())
        self.assertEqual(config['base_currency_code'], 'USD')
        self.assertEqual(config['system_language'], 'ar')
        self.assertEqual(config['timezone'], 'Asia/Dubai')

    def test_format_tenant_number_eu_and_parentheses_negative(self):
        config = dict(DEFAULT_TENANT_SYSTEM_CONFIG)
        config['number_format'] = '1.234,56'
        config['negative_format'] = '(100)'
        self.assertEqual(format_tenant_number('1234.5', config), '1.234,50')
        self.assertEqual(format_tenant_number('-99.9', config), '(99,90)')

    def test_format_tenant_currency(self):
        config = dict(DEFAULT_TENANT_SYSTEM_CONFIG)
        config['base_currency_code'] = 'SAR'
        self.assertEqual(format_tenant_currency('200', 'SAR', config), 'SAR 200.00')

    def test_format_tenant_date_respects_config_pattern(self):
        config = dict(DEFAULT_TENANT_SYSTEM_CONFIG)
        config['date_format'] = 'YYYY-MM-DD'
        value = date(2026, 6, 15)
        self.assertEqual(format_tenant_date(value, config), '2026-06-15')

    def test_activate_tenant_system_config_sets_timezone(self):
        config = dict(DEFAULT_TENANT_SYSTEM_CONFIG)
        config['timezone'] = 'Asia/Riyadh'
        activate_tenant_system_config(config)
        now = timezone.localtime(datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo('UTC')))
        self.assertEqual(str(now.tzinfo), 'Asia/Riyadh')

    def test_tenant_system_config_for_js(self):
        payload = tenant_system_config_for_js(config_dict_from_organization_profile(_OrgStub()))
        self.assertEqual(payload['js_locale'], 'ar-SA')
        self.assertTrue(payload['is_rtl'])

    def test_middleware_attaches_config_for_tenant_paths(self):
        factory = RequestFactory()
        request = factory.get('/tenant/administration/subscription-billing/')
        request.tenant_workspace_registry = object()
        request.tenant_system_config = config_dict_from_organization_profile(_OrgStub())

        captured = {}

        def get_response(req):
            captured['config'] = getattr(req, 'tenant_system_config', None)
            captured['tz'] = str(timezone.get_current_timezone())
            from django.utils import translation

            captured['lang'] = translation.get_language()
            return object()

        middleware = TenantSystemConfigurationMiddleware(get_response)
        middleware(request)
        self.assertEqual(captured['config']['base_currency_code'], 'USD')
        self.assertEqual(captured['lang'], 'ar')
