from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv46_address
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect

from iroad_frontend.cms_text import localized_cms_field
from iroad_frontend.models import (
    AboutPageContent,
    ContactPageContent,
    ContactSubmission,
    HomePageContent,
    MobileAboutUsPageContent,
    PricingPageContent,
    PrivacyPolicyPageContent,
    TermsConditionsPageContent,
)


def get_lang_context(request) -> dict:
    """
    Detect language from:
    1. ?lang=ar or ?lang=en query param
    2. Session lang preference
    3. Default: en

    Returns dict with lang and dir keys.
    """
    lang = (request.GET.get('lang') or '').strip().lower()
    if lang not in ('en', 'ar'):
        lang = request.session.get('frontend_lang', 'en')
    else:
        request.session['frontend_lang'] = lang
    if lang not in ('en', 'ar'):
        lang = 'en'
    return {
        'lang': lang,
        'dir': 'rtl' if lang == 'ar' else 'ltr',
    }


class HomePageView(View):
    def get(self, request):
        home = HomePageContent.get_singleton()
        service_cards = home.service_cards.filter(is_active=True).order_by('order')
        pricing_tiers = home.pricing_tiers.filter(is_active=True).order_by('order')
        testimonials = home.testimonials.filter(is_active=True).order_by('order')
        map_locations = home.map_locations.filter(is_active=True).order_by('order')[:4]
        pricing_benefits = home.pricing_benefits.filter(is_active=True).order_by('order')
        context = {
            'home': home,
            'service_cards': service_cards,
            'pricing_tiers': pricing_tiers,
            'pricing_benefits': pricing_benefits,
            'testimonials': testimonials,
            'map_locations': map_locations,
        }
        context.update(get_lang_context(request))
        return render(
            request,
            'iroad_frontend/home/index.html',
            context,
        )


class AboutPageView(View):
    def get(self, request):
        about = AboutPageContent.get_singleton()
        home = HomePageContent.get_singleton()
        context = {
            'about': about,
            'home': home,
            'pillars': about.approach_pillars.filter(
                is_active=True).order_by('order'),
            'how_steps': about.how_work_steps.filter(
                is_active=True).order_by('order'),
            'faq_items': about.faq_items.filter(
                is_active=True).order_by('order'),
        }
        context.update(get_lang_context(request))
        return render(
            request,
            'iroad_frontend/about/index.html',
            context,
        )


class PricingPageView(View):
    def get(self, request):
        pricing = PricingPageContent.get_singleton()
        home = HomePageContent.get_singleton()

        pricing_tiers = home.pricing_tiers.filter(
            is_active=True).order_by('order')
        testimonials = home.testimonials.filter(
            is_active=True).order_by('order')
        map_locations = home.map_locations.filter(
            is_active=True).order_by('order')
        pricing_benefits = home.pricing_benefits.filter(
            is_active=True).order_by('order')

        context = {
            'pricing': pricing,
            'home': home,
            'pricing_tiers': pricing_tiers,
            'pricing_benefits': pricing_benefits,
            'interactive_steps': pricing.interactive_steps.filter(
                is_active=True).order_by('order'),
            'testimonials': testimonials,
            'map_locations': map_locations,
            'faq_items': pricing.faq_items.filter(
                is_active=True).order_by('order'),
        }
        context.update(get_lang_context(request))
        return render(
            request,
            'iroad_frontend/pricing/index.html',
            context,
        )


class ContactPageView(View):
    def get(self, request):
        contact = ContactPageContent.get_singleton()
        home = HomePageContent.get_singleton()
        context = {
            'contact': contact,
            'home': home,
            'form_success': request.GET.get('success') == '1',
            'form_error': request.GET.get('error') == '1',
        }
        context.update(get_lang_context(request))
        return render(
            request,
            'iroad_frontend/contact/index.html',
            context,
        )


class PrivacyPolicyView(View):
    """Public privacy policy page (CMS singleton). Not linked from site nav.

    Pass ``?remove_header_footer=true`` to hide site header/footer and the
    page hero (WebView / embedded use), same as terms and mobile about us.
    """

    def get(self, request):
        privacy = PrivacyPolicyPageContent.get_singleton()
        home = HomePageContent.get_singleton()
        context = {
            'privacy': privacy,
            'home': home,
        }
        context.update(get_lang_context(request))
        lang = context['lang']
        context['page_header_use_generic'] = True
        context['page_h1'] = localized_cms_field(
            privacy, 'page_header_h1', lang)
        context['breadcrumb_current'] = localized_cms_field(
            privacy, 'breadcrumb_current', lang)
        context['remove_header_footer'] = (
            request.GET.get('remove_header_footer') == 'true'
        )
        return render(
            request,
            'iroad_frontend/privacy_policy/index.html',
            context,
        )


class TermsConditionsView(View):
    """Public terms & conditions page (CMS singleton). Not linked from site nav.

    Pass ``?remove_header_footer=true`` to hide site header/footer and the
    page hero (WebView / embedded use), same as privacy and mobile about us.
    """

    def get(self, request):
        terms_conditions = TermsConditionsPageContent.get_singleton()
        home = HomePageContent.get_singleton()
        context = {
            'terms_conditions': terms_conditions,
            'home': home,
        }
        context.update(get_lang_context(request))
        lang = context['lang']
        context['page_header_use_generic'] = True
        context['page_h1'] = localized_cms_field(
            terms_conditions, 'page_header_h1', lang)
        context['breadcrumb_current'] = localized_cms_field(
            terms_conditions, 'breadcrumb_current', lang)
        context['remove_header_footer'] = (
            request.GET.get('remove_header_footer') == 'true'
        )
        return render(
            request,
            'iroad_frontend/terms_conditions/index.html',
            context,
        )


class MobileAboutUsView(View):
    """Public mobile About Us page (CMS singleton). URL-only; not linked from nav."""

    def get(self, request):
        mobile_about_us = MobileAboutUsPageContent.get_singleton()
        home = HomePageContent.get_singleton()
        context = {
            'mobile_about_us': mobile_about_us,
            'home': home,
        }
        context.update(get_lang_context(request))
        lang = context['lang']
        context['page_header_use_generic'] = True
        context['page_h1'] = localized_cms_field(
            mobile_about_us, 'page_header_h1', lang)
        context['breadcrumb_current'] = localized_cms_field(
            mobile_about_us, 'breadcrumb_current', lang)
        context['remove_header_footer'] = (
            request.GET.get('remove_header_footer') == 'true'
        )
        return render(
            request,
            'iroad_frontend/mobile_about_us/index.html',
            context,
        )


def _client_ip_for_submission(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        ip = x_forwarded.split(',')[0].strip()
    else:
        ip = (request.META.get('REMOTE_ADDR') or '').strip()
    if not ip:
        return None
    try:
        validate_ipv46_address(ip)
    except ValidationError:
        return None
    return ip


@method_decorator(csrf_protect, name='dispatch')
class ContactFormSubmitView(View):
    """
    Handles demo request form POST.
    Saves ContactSubmission and redirects.
    """

    def post(self, request):
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip()
        message = request.POST.get('message', '').strip()
        consent = request.POST.get('consent', '') == 'on'

        if not email or not first_name:
            return redirect('/contact/?error=1')

        ip = _client_ip_for_submission(request)

        ContactSubmission.objects.create(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
            message=message,
            consent_given=consent,
            ip_address=ip,
        )

        return redirect('/contact/?success=1')


def page_not_found(request, exception=None):
    """
    Custom 404 (handler404 in root URLconf).
    Uses the same chrome as the public site: base layout, header/footer,
    and CMS-driven nav/footer via HomePageContent singleton.
    """
    home = HomePageContent.get_singleton()
    ctx = {'home': home}
    ctx.update(get_lang_context(request))
    return render(
        request,
        'iroad_frontend/errors/404.html',
        ctx,
        status=404,
    )
