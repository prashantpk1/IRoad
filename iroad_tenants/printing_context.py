"""Shared context helpers for tenant PDF print templates."""
from __future__ import annotations

from django.conf import settings
from django.templatetags.static import static

from tenant_workspace.models import OrganizationProfile

PRINT_NA = '—'

IROUTE_LOGO_BLUE_STATIC = 'tenantdesign/image/brand/iroute-logo-blue.svg'
IROUTE_LOGO_WHITE_STATIC = 'tenantdesign/image/brand/iroute-logo-white.svg'


def _organization_profile():
    return OrganizationProfile.objects.order_by('-updated_at').first()


def _org_logo_url(profile) -> str:
    if profile is None or not profile.logo_file:
        return ''
    try:
        return profile.logo_file.url
    except (ValueError, AttributeError):
        return ''


def _static_asset_url(static_path: str) -> str:
    return absolute_media_url(static(static_path))


def build_brand_print_context() -> dict:
    """
    Official IRoute logo assets (see IROAD DOC/iroute_logo/).

    Blue logo on light/white print backgrounds; white logo on Dynamic Blue (#3B82F6).
    """
    return {
        'logo_blue_url': _static_asset_url(IROUTE_LOGO_BLUE_STATIC),
        'logo_white_url': _static_asset_url(IROUTE_LOGO_WHITE_STATIC),
        'logo_blue_on_light': True,
    }


def build_org_print_context() -> dict:
    profile = _organization_profile()
    tenant_logo_url = absolute_media_url(_org_logo_url(profile))
    brand = build_brand_print_context()
    return {
        'org': {
            'name_ar': (profile.name_ar if profile else '') or PRINT_NA,
            'name_en': (profile.name_en if profile else '') or PRINT_NA,
            'logo_url': tenant_logo_url,
            'cr_number': (profile.cr_number if profile else '') or PRINT_NA,
            'tax_number': (profile.tax_number if profile else '') or PRINT_NA,
        },
        'brand': brand,
        'print_na': PRINT_NA,
        'currency_code': (
            (profile.base_currency_code if profile else '') or 'SAR'
        ),
    }


def enrich_print_template_context(context: dict | None) -> dict:
    merged = build_org_print_context()
    if context:
        merged.update(context)
    return merged


def absolute_media_url(relative_url: str) -> str:
    """Build an absolute URL for wkhtmltopdf when rendering uploaded media."""
    url = (relative_url or '').strip()
    if not url:
        return ''
    if url.startswith(('http://', 'https://', 'data:')):
        return url
    base = (getattr(settings, 'MEDIA_URL', '') or '/media/').rstrip('/')
    if not url.startswith('/'):
        url = f'{base}/{url.lstrip("/")}'
    site = (getattr(settings, 'SITE_URL', '') or '').rstrip('/')
    if site and url.startswith('/'):
        return f'{site}{url}'
    return url
