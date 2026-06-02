from django import template
from django.utils import translation

register = template.Library()


@register.simple_tag(takes_context=True)
def bilingual_field(context, obj, en_field, ar_field, default=''):
    """Show the *_ar value in Arabic only when it is populated; otherwise keep English."""
    if obj is None:
        return default
    lang = (context.get('LANGUAGE_CODE') or translation.get_language() or 'en')[:2]
    if lang == 'ar':
        ar_value = getattr(obj, ar_field, None)
        if ar_value not in (None, ''):
            return ar_value
    en_value = getattr(obj, en_field, None)
    if en_value not in (None, ''):
        return en_value
    return default


@register.simple_tag
def english_only(value, default='-'):
    """Render stored data values without UI translation (for table body cells)."""
    if value in (None, ''):
        return default
    return value
