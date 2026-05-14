"""
Bilingual CMS helpers: pick *_ar vs *_en using ``lang`` from template context.
"""
from django import template
from django.utils.safestring import mark_safe

from iroad_frontend.cms_text import localized_cms_field

register = template.Library()


@register.simple_tag(takes_context=True)
def cms_txt(context, obj, base):
    """
    Return localized text for a model field pair ``{base}_en`` / ``{base}_ar``.

    Uses ``lang`` from context (set by ``get_lang_context``). Falls back to the
    other language when the preferred column is empty.
    """
    lang = context.get('lang') or 'en'
    return localized_cms_field(obj, base, lang)


@register.simple_tag(takes_context=True)
def cms_richtext(context, obj, base):
    """
    Localized HTML body for ``{base}_en`` / ``{base}_ar`` (e.g. ``content``).

    Same language selection and cross-language fallback as ``cms_txt`` /
    ``localized_cms_field``. Marked safe for intentional CMS HTML output.
    """
    lang = context.get('lang') or 'en'
    return mark_safe(localized_cms_field(obj, base, lang))
