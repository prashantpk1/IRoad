from django.conf import settings
from django.urls import path

from iroad_frontend.error_views import error_preview
from iroad_frontend.views import (
    AboutPageView,
    ContactFormSubmitView,
    ContactPageView,
    HomePageView,
    MobileAboutUsView,
    PricingPageView,
    PrivacyPolicyView,
    TermsConditionsView,
)

app_name = 'iroad_frontend'

urlpatterns = [
    path('about/', AboutPageView.as_view(), name='about'),
    path('pricing/', PricingPageView.as_view(), name='pricing'),
    path('contact/', ContactPageView.as_view(), name='contact'),
    path(
        'contact/submit/',
        ContactFormSubmitView.as_view(),
        name='contact_submit',
    ),
    path(
        'privacy-policy/',
        PrivacyPolicyView.as_view(),
        name='privacy_policy',
    ),
    path(
        'terms-and-conditions/',
        TermsConditionsView.as_view(),
        name='terms_conditions',
    ),
    path(
        'mobile-about-us/',
        MobileAboutUsView.as_view(),
        name='mobile_about_us',
    ),
    path('', HomePageView.as_view(), name='home'),
]

if settings.DEBUG:
    urlpatterns += [
        path(
            '__preview__/error/<int:code>/',
            error_preview,
            name='error_preview',
        ),
        path(
            '__preview__/portal-error/<int:code>/',
            error_preview,
            name='portal_error_preview',
        ),
    ]
